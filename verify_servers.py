import time, urllib.request, json, sys

def check(url, expect_json=False):
    for i in range(40):
        try:
            r = urllib.request.urlopen(url, timeout=5)
            b = r.read()
            if expect_json:
                d = json.loads(b)
                print(url, r.status, "ok=", d.get("ok"), "app=", d.get("app", {}).get("code"))
            else:
                txt = b.decode("utf-8", "replace")
                print(url, r.status, "has-root-div=", 'id="app"' in txt, "bytes=", len(b))
            return
        except Exception as e:
            if i == 39:
                print(url, "FAILED", e)
                sys.exit(1)
            time.sleep(1)

check("http://127.0.0.1:5173/")
check("http://127.0.0.1:5173/api/runtime/demo-shop/", expect_json=True)
