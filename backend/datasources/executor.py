"""数据源执行器：secret 编码 / SQL 白名单守卫 / rest|sql|static 执行。"""
from __future__ import annotations

import base64
import binascii
import re
from typing import Any

from django.db import connection
from rest_framework.exceptions import ValidationError

from wp_utils import apply_transform, build_query_string, get_json_path, http_request, render_template

SECRET_PREFIX = "WPSECRET:"
SECRET_KEY_RE = re.compile(r"(secret|password|passwd|token|api_?key|authorization|credential)", re.I)
SQL_FORBIDDEN_RE = re.compile(r"(?is)\b(insert|update|delete|drop|alter|truncate|create|grant|revoke|exec|execute|merge|replace)\b")


def encode_secret(value: str) -> str:
    if value.startswith(SECRET_PREFIX):
        return value
    return SECRET_PREFIX + base64.b64encode(str(value).encode("utf-8")).decode("ascii")


def decode_secret(value: str) -> str:
    if not isinstance(value, str) or not value.startswith(SECRET_PREFIX):
        return value
    raw = value[len(SECRET_PREFIX):]
    try:
        return base64.b64decode(raw.encode("ascii")).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return raw


def _walk(obj: Any, *, encode: bool):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(v, str) and encode and SECRET_KEY_RE.search(str(k)) and not v.startswith(SECRET_PREFIX):
                out[k] = encode_secret(v)
            else:
                out[k] = _walk(v, encode=encode)
        return out
    if isinstance(obj, list):
        return [_walk(v, encode=encode) for v in obj]
    if isinstance(obj, str) and not encode:
        return decode_secret(obj)
    return obj


def encode_secrets(config: dict) -> dict:
    """保存前：密钥类字段值 base64+marker 编码。"""
    return _walk(config or {}, encode=True)


def decode_secrets(config: dict) -> dict:
    """执行前：解码所有 marker 值。"""
    return _walk(config or {}, encode=False)


# ---------------------------------------------------------------- SQL 守卫

def assert_select_only(sql: str) -> None:
    """仅允许单条 SELECT/WITH 查询；拒绝写操作、多语句与注释。"""
    if not sql or not sql.strip():
        raise ValidationError({"detail": "SQL 不能为空"})
    if "--" in sql or "/*" in sql:
        raise ValidationError({"detail": "禁止 SQL 注释"})
    if ";" in sql.strip().rstrip(";"):
        raise ValidationError({"detail": "只允许单条 SQL 语句"})
    stripped = sql.strip().rstrip(";")
    if not re.match(r"(?is)^\s*(select|with)\b", stripped):
        raise ValidationError({"detail": "只允许 SELECT 查询"})
    if SQL_FORBIDDEN_RE.search(stripped):
        raise ValidationError({"detail": "SQL 包含禁止的写操作关键字"})


_PARAM_RE = re.compile(r"\{(\w+)\}")


def _sql_params(query: str, params: dict) -> tuple[str, list]:
    """把 `{name}` 占位替换为 %s 参数（SQLite/Postgres 通用）。"""
    values: list = []
    missing: list[str] = []

    def _sub(m: re.Match) -> str:
        name = m.group(1)
        if name in params:
            values.append(params[name])
            return "%s"
        missing.append(name)
        return m.group(0)

    prepared = _PARAM_RE.sub(_sub, query)
    if missing:
        raise ValidationError({"detail": f"SQL 缺少参数: {', '.join(sorted(set(missing)))}"})
    return prepared, values


def execute_sql(query: str, params: dict) -> list[dict]:
    assert_select_only(query)
    prepared, values = _sql_params(query, params or {})
    with connection.cursor() as cursor:
        cursor.execute(prepared, values or None)
        columns = [d[0] for d in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]


# ---------------------------------------------------------------- 执行入口

def _rest_url_and_params(cfg: dict, params: dict) -> tuple[str, dict]:
    url = render_template(str(cfg.get("url") or ""), params)
    # URL 中未出现的参数合并进 query string
    merged = dict(params or {})
    return url, merged


def execute_rest(cfg: dict, params: dict, *, is_test: bool = False) -> dict:
    cfg = dict(cfg or {})
    method = str(cfg.get("method") or ("GET" if is_test else "GET")).upper()
    if is_test:
        method = "GET"
    url, params = _rest_url_and_params(cfg, params or {})
    extra_qs = {k: v for k, v in params.items() if "{%s}" % k not in url and "{{%s}}" % k not in url}
    if extra_qs:
        sep = "&" if "?" in url else "?"
        url = url + sep + build_query_string(extra_qs)
    headers = {k: render_template(str(v), params or {}) for k, v in (cfg.get("headers") or {}).items()}
    # 认证：auth_type=bearer → Authorization: Bearer <token>；basic → Basic base64(user:pass)
    auth_type = str(cfg.get("auth_type") or "").lower()
    if auth_type == "bearer":
        token = cfg.get("token") or cfg.get("api_key") or ""
        if token:
            headers["Authorization"] = f"Bearer {token}"
    elif auth_type == "basic":
        import base64 as _b64

        user = str(cfg.get("username") or "")
        password = str(cfg.get("password") or "")
        headers["Authorization"] = "Basic " + _b64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    body = cfg.get("body")
    if isinstance(body, (dict, list)):
        import json as _json

        body = _json.dumps(body, ensure_ascii=False)
    if body:
        body = render_template(str(body), params or {}).encode("utf-8")
    if isinstance(body, str):
        body = body.encode("utf-8")
    if "Content-Type" not in headers and body:
        headers["Content-Type"] = "application/json"
    timeout = float(cfg.get("timeout") or 5.0)
    status_code, text = http_request(url, method=method, headers=headers, body=body, timeout=timeout)
    data = None
    try:
        import json as _json

        data = _json.loads(text)
    except (ValueError, TypeError):
        data = text
    ok = 200 <= status_code < 400
    return {"ok": ok, "status": status_code, "data": data}


def _external_params(query: str, params: dict, style: str) -> tuple[str, list]:
    values: list = []
    missing: list[str] = []

    def _sub(m: re.Match) -> str:
        name = m.group(1)
        if name in params:
            values.append(params[name])
            return style
        missing.append(name)
        return m.group(0)

    prepared = _PARAM_RE.sub(_sub, query)
    if missing:
        raise ValidationError({"detail": f"SQL 缺少参数: {', '.join(sorted(set(missing)))}"})
    return prepared, values


def execute_external_db(ds_type: str, cfg: dict, params: dict) -> list[dict]:
    """执行外部数据库只读查询。驱动按需导入，配置密码已在 decode_secrets 中解密。"""
    host = str(cfg.get("host") or "").strip()
    database = str(cfg.get("database") or "").strip()
    username = str(cfg.get("username") or "").strip()
    password = str(cfg.get("password") or "")
    query = str(cfg.get("query") or "").strip().rstrip(";")
    if not host or not database:
        raise ValidationError({"detail": "外部数据库需要 host 和 database"})
    if not query:
        raise ValidationError({"detail": "外部数据库需要 query"})
    assert_select_only(query)
    try:
        max_rows = min(5000, max(1, int(cfg.get("max_rows") or 500)))
        timeout = min(60, max(1, int(cfg.get("timeout") or 8)))
    except (TypeError, ValueError):
        max_rows, timeout = 500, 8

    if ds_type in ("mysql", "postgres"):
        sql, values = _external_params(query, params or {}, "%s")
    else:
        sql, values = _external_params(query, params or {}, "?")

    if ds_type == "postgres":
        try:
            import psycopg
        except ImportError:
            try:
                import psycopg2 as psycopg  # type: ignore
            except ImportError as exc:
                raise ValidationError({"detail": "PostgreSQL 驱动未安装：请安装 psycopg[binary] 或 psycopg2-binary"}) from exc
        try:
            conn = psycopg.connect(
                host=host, port=int(cfg.get("port") or 5432), dbname=database,
                user=username, password=password, connect_timeout=timeout,
                sslmode=str(cfg.get("ssl") or "prefer"),
            )
        except Exception as exc:  # noqa: BLE001
            raise ValidationError({"detail": f"PostgreSQL 连接失败: {exc}"}) from exc
        try:
            with conn.cursor() as cur:
                cur.execute(sql, values or None)
                columns = [getattr(d, "name", d[0]) for d in cur.description] if cur.description else []
                rows = cur.fetchmany(max_rows)
                return [dict(zip(columns, row)) for row in rows]
        finally:
            conn.close()

    if ds_type == "mysql":
        try:
            import pymysql
            from pymysql.cursors import DictCursor
        except ImportError as exc:
            raise ValidationError({"detail": "MySQL 驱动未安装：请安装 PyMySQL"}) from exc
        try:
            conn = pymysql.connect(
                host=host, port=int(cfg.get("port") or 3306), user=username, password=password,
                database=database, charset="utf8mb4", cursorclass=DictCursor,
                connect_timeout=timeout, read_timeout=timeout,
            )
        except Exception as exc:  # noqa: BLE001
            raise ValidationError({"detail": f"MySQL 连接失败: {exc}"}) from exc
        try:
            with conn.cursor() as cur:
                cur.execute(sql, values or None)
                return list(cur.fetchmany(max_rows))
        finally:
            conn.close()

    if ds_type == "sqlserver":
        try:
            import pyodbc
        except ImportError as exc:
            raise ValidationError({"detail": "SQL Server 驱动未安装：请安装 pyodbc 并安装 ODBC Driver 18"}) from exc
        driver = str(cfg.get("driver") or "ODBC Driver 18 for SQL Server")
        conn_str = (
            f"DRIVER={{{driver}}};SERVER={host},{int(cfg.get('port') or 1433)};"
            f"DATABASE={database};UID={username};PWD={password};"
            f"Encrypt={str(cfg.get('encrypt') or 'yes')};TrustServerCertificate={str(cfg.get('trust_cert') or 'yes')};"
            f"Connection Timeout={timeout}"
        )
        try:
            conn = pyodbc.connect(conn_str, timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            raise ValidationError({"detail": f"SQL Server 连接失败: {exc}"}) from exc
        try:
            cur = conn.cursor()
            cur.execute(sql, values or None)
            columns = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchmany(max_rows)
            return [dict(zip(columns, row)) for row in rows]
        finally:
            conn.close()

    raise ValidationError({"detail": f"未知外部数据库类型 {ds_type}"})


def list_external_schema(ds_type: str, cfg: dict) -> list[dict]:
    """读取外部数据库的 schema/table/column 结构（只读）。"""
    host = str(cfg.get("host") or "").strip()
    database = str(cfg.get("database") or "").strip()
    username = str(cfg.get("username") or "").strip()
    password = str(cfg.get("password") or "")
    if not host or not database:
        raise ValidationError({"detail": "外部数据库需要 host 和 database"})
    timeout = min(30, max(3, int(cfg.get("timeout") or 8)))
    if ds_type == "postgres":
        try:
            import psycopg
        except ImportError:
            try:
                import psycopg2 as psycopg  # type: ignore
            except ImportError as exc:
                raise ValidationError({"detail": "PostgreSQL 驱动未安装"}) from exc
        conn = psycopg.connect(
            host=host, port=int(cfg.get("port") or 5432), dbname=database,
            user=username, password=password, connect_timeout=timeout,
            sslmode=str(cfg.get("ssl") or "prefer"),
        )
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT table_schema, table_name, column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                    ORDER BY table_schema, table_name, ordinal_position
                """)
                rows = cur.fetchall()
        finally:
            conn.close()
    elif ds_type == "mysql":
        try:
            import pymysql
        except ImportError as exc:
            raise ValidationError({"detail": "MySQL 驱动未安装"}) from exc
        conn = pymysql.connect(
            host=host, port=int(cfg.get("port") or 3306), user=username, password=password,
            database=database, connect_timeout=timeout, read_timeout=timeout,
        )
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT table_schema, table_name, column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = %s
                    ORDER BY table_name, ordinal_position
                """, (database,))
                rows = cur.fetchall()
        finally:
            conn.close()
    elif ds_type == "sqlserver":
        try:
            import pyodbc
        except ImportError as exc:
            raise ValidationError({"detail": "SQL Server 驱动未安装"}) from exc
        driver = str(cfg.get("driver") or "ODBC Driver 18 for SQL Server")
        conn = pyodbc.connect(
            f"DRIVER={{{driver}}};SERVER={host},{int(cfg.get('port') or 1433)};DATABASE={database};"
            f"UID={username};PWD={password};Encrypt=yes;TrustServerCertificate=yes;Connection Timeout={timeout}",
            timeout=timeout,
        )
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT table_schema, table_name, column_name, data_type, is_nullable
                FROM information_schema.columns
                ORDER BY table_schema, table_name, ordinal_position
            """)
            rows = cur.fetchall()
        finally:
            conn.close()
    else:
        raise ValidationError({"detail": "该数据源不支持结构浏览"})

    tables: dict[tuple[str, str], dict] = {}
    for schema, table, column, data_type, nullable in rows:
        key = (str(schema), str(table))
        item = tables.setdefault(key, {"schema": key[0], "name": key[1], "columns": []})
        item["columns"].append({"name": str(column), "type": str(data_type), "nullable": str(nullable).upper() == "YES"})
    return list(tables.values())


def execute_static(cfg: dict, params: dict) -> dict:
    data = (cfg or {}).get("data")
    return {"ok": True, "status": 200, "data": data}


def _mapped_row(row: Any, mapping: dict) -> Any:
    if not isinstance(row, dict):
        return row
    out = dict(row)
    for target, path in mapping.items():
        if not isinstance(path, str):
            continue
        out[str(target)] = get_json_path(row, path)
    return out


def _flatten_value(value: Any, prefix: str, out: dict) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            name = f"{prefix}_{key}" if prefix else str(key)
            _flatten_value(child, name, out)
    else:
        out[prefix] = value


def flatten_json_rows(data: Any) -> Any:
    """把每行嵌套对象拍平成 a_b_c 列；数组保持原值。"""
    if not isinstance(data, list):
        return data
    rows = []
    for row in data:
        if not isinstance(row, dict):
            rows.append(row)
            continue
        flat: dict = {}
        _flatten_value(row, "", flat)
        rows.append(flat)
    return rows


def apply_response_map(data: Any, mapping: dict) -> Any:
    """config.response_map: {目标字段: 源字段路径}，对对象/数组逐行映射。"""
    if not isinstance(mapping, dict) or not mapping:
        return data
    if isinstance(data, list):
        return [_mapped_row(row, mapping) for row in data]
    return _mapped_row(data, mapping)


def run_datasource(datasource, params: dict, *, is_test: bool = False) -> dict:
    """执行数据源，返回 {ok, status, data, error}。"""
    cfg = decode_secrets(datasource.config or {})
    try:
        if datasource.type == "rest":
            if not (cfg.get("url") or "").strip():
                raise ValidationError({"detail": "rest 数据源缺少 config.url"})
            result = execute_rest(cfg, params, is_test=is_test)
        elif datasource.type == "sql":
            result = {"ok": True, "status": 200, "data": execute_sql(str(cfg.get("query") or ""), params or {})}
        elif datasource.type in ("mysql", "postgres", "sqlserver"):
            result = {"ok": True, "status": 200, "data": execute_external_db(datasource.type, cfg, params or {})}
        elif datasource.type == "static":
            result = execute_static(cfg, params)
        elif datasource.type == "websocket":
            if not is_test:
                raise ValidationError({"detail": "WebSocket 数据源由浏览器运行时订阅，不支持服务端查询"})
            result = {"ok": True, "status": 200, "data": []}
        else:
            raise ValidationError({"detail": f"未知数据源类型 {datasource.type}"})
        data = result.get("data")
        data_path = str(cfg.get("data_path") or "").strip()
        if data_path:
            data = get_json_path(data, data_path)
        data = apply_response_map(data, cfg.get("response_map") or {})
        if cfg.get("flatten"):
            data = flatten_json_rows(data)
        if datasource.transform:
            data = apply_transform(data, datasource.transform)
        return {"ok": result["ok"], "status": result.get("status"), "data": data, "error": ""}
    except ValidationError as e:
        detail = e.detail.get("detail") if isinstance(e.detail, dict) else e.detail
        return {"ok": False, "status": None, "data": None, "error": str(detail)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "status": None, "data": None, "error": f"{type(e).__name__}: {e}"}
