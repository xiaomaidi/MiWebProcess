<template>
  <div class="wp-admin-page">
    <div class="wp-page-header">
      <h2>用户管理</h2>
      <el-button type="primary" @click="openInvite">邀请用户</el-button>
    </div>

    <el-card>
      <div class="wp-filter-bar">
        <el-input
          v-model="query"
          placeholder="按用户名/邮箱搜索"
          clearable
          style="width: 240px"
          @keyup.enter="reload"
          @clear="reload"
        />
        <el-button @click="reload">查询</el-button>
        <el-select v-model="roleFilter" size="small" clearable placeholder="全部角色" style="width: 140px" @change="reload">
          <el-option label="超级管理员" value="superuser" />
          <el-option label="平台管理员" value="platform_admin" />
          <el-option label="普通用户" value="normal" />
        </el-select>
        <el-select v-model="activeFilter" size="small" clearable placeholder="全部状态" style="width: 120px" @change="reload">
          <el-option label="启用" value="1" />
          <el-option label="禁用" value="0" />
        </el-select>
      </div>

      <div v-if="selectedIds.length" class="wp-batch-bar">
        <span>已选 {{ selectedIds.length }} 个用户</span>
        <el-button size="small" @click="batch('enable')">批量启用</el-button>
        <el-button size="small" type="warning" plain @click="batch('disable')">批量禁用</el-button>
        <el-button size="small" type="danger" plain @click="batch('delete')">批量删除</el-button>
      </div>

      <el-table :data="users" v-loading="loading" border stripe @selection-change="onSelectionChange">
        <el-table-column type="selection" width="44" />
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="username" label="用户名" min-width="160">
          <template #default="{ row }">
            {{ row.username }}
            <el-tag v-if="row.is_platform_admin" size="small" type="warning" effect="plain" style="margin-left: 6px">平台管理员</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="姓名" min-width="140">
          <template #default="{ row }">{{ [row.first_name, row.last_name].filter(Boolean).join(" ") || "—" }}</template>
        </el-table-column>
        <el-table-column prop="email" label="邮箱" min-width="200" />
        <el-table-column label="最后登录" width="170">
          <template #default="{ row }">{{ row.last_login || "—" }}</template>
        </el-table-column>
        <el-table-column label="超级管理员" width="120">
          <template #default="{ row }">
            <el-switch
              :model-value="row.is_superuser"
              :disabled="row.id === auth.user?.id"
              :loading="row.id === switchingId"
              @change="(v: boolean) => toggleSuperuser(row, v)"
            />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="390" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openAccess(row)">权限</el-button>
            <el-button size="small" @click="openEdit(row)">编辑资料</el-button>
            <el-button
              size="small"
              :type="row.is_active ? 'danger' : 'success'"
              plain
              :disabled="row.id === auth.user?.id"
              @click="toggleActive(row)"
            >{{ row.is_active ? "禁用" : "启用" }}</el-button>
            <el-button
              size="small"
              type="danger"
              plain
              :disabled="row.id === auth.user?.id"
              @click="deleteUser(row)"
            >删除</el-button>
          </template>
        </el-table-column>
        <template #empty><el-empty description="暂无用户" :image-size="60" /></template>
      </el-table>

      <div class="wp-pager">
        <el-pagination
          v-model:current-page="page"
          :page-size="size"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="load"
        />
      </div>
    </el-card>

    <el-dialog v-model="editVisible" title="编辑用户资料" width="480px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="用户名">
          <el-input :model-value="target?.username" disabled />
        </el-form-item>
        <el-form-item label="姓名（first）">
          <el-input v-model="form.first_name" />
        </el-form-item>
        <el-form-item label="姓名（last）">
          <el-input v-model="form.last_name" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="form.email" />
        </el-form-item>
        <el-form-item label="超级管理员">
          <el-switch
            v-model="form.is_superuser"
            :disabled="target?.id === auth.user?.id"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="inviteVisible" title="邀请用户" width="520px" :close-on-click-modal="false">
      <template v-if="inviteResult">
        <el-alert type="success" :closable="false" show-icon title="用户已创建，请把临时密码发给对方" />
        <el-descriptions :column="1" border style="margin-top: 12px">
          <el-descriptions-item label="用户名">{{ inviteResult.username }}</el-descriptions-item>
          <el-descriptions-item label="临时密码">
            <el-input :model-value="inviteResult.temporary_password" readonly>
              <template #append><el-button @click="copyPassword">复制</el-button></template>
            </el-input>
          </el-descriptions-item>
        </el-descriptions>
        <p class="wp-muted">请通过安全渠道发送；用户登录后建议尽快修改密码。</p>
      </template>
      <el-form v-else :model="inviteForm" label-width="90px">
        <el-form-item label="用户名" required><el-input v-model="inviteForm.username" /></el-form-item>
        <el-form-item label="邮箱"><el-input v-model="inviteForm.email" /></el-form-item>
        <el-form-item label="姓名"><el-input v-model="inviteForm.first_name" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="inviteVisible = false">关闭</el-button>
        <el-button v-if="!inviteResult" type="primary" :loading="inviteSaving" @click="createInvite">创建邀请</el-button>
      </template>
    </el-dialog>

    <UserAccessDrawer v-model="accessVisible" :user="accessUser" @changed="load" />
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { api } from "@/api";
import { useAuthStore } from "@/store/auth";
import UserAccessDrawer from "./UserAccessDrawer.vue";
import type { UserInfo } from "@/types";

const auth = useAuthStore();

const loading = ref(false);
const saving = ref(false);
const switchingId = ref<number | null>(null);
const users = ref<UserInfo[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);
const query = ref("");
const roleFilter = ref("");
const activeFilter = ref("");

const editVisible = ref(false);
const target = ref<UserInfo | null>(null);
const accessVisible = ref(false);
const accessUser = ref<UserInfo | null>(null);
const selectedIds = ref<number[]>([]);
const inviteVisible = ref(false);
const inviteSaving = ref(false);
const inviteResult = ref<any>(null);
const inviteForm = reactive({ username: "", email: "", first_name: "" });
const form = reactive({ first_name: "", last_name: "", email: "", is_superuser: false });

async function load() {
  loading.value = true;
  try {
    const qs = new URLSearchParams({ page: String(page.value), size: String(size.value) });
    if (query.value.trim()) qs.set("q", query.value.trim());
    if (roleFilter.value) qs.set("role", roleFilter.value);
    if (activeFilter.value) qs.set("is_active", activeFilter.value);
    const data = await api.get<unknown>(`/auth/users/?${qs.toString()}`);
    if (Array.isArray(data)) {
      users.value = data as UserInfo[];
      total.value = data.length;
    } else {
      const p = data as { count: number; results: UserInfo[] } | null;
      users.value = p?.results ?? [];
      total.value = p?.count ?? 0;
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "加载用户列表失败");
  } finally {
    loading.value = false;
  }
}

function reload() {
  page.value = 1;
  load();
}

function openAccess(row: UserInfo) {
  accessUser.value = row;
  accessVisible.value = true;
}

function onSelectionChange(rows: UserInfo[]) {
  selectedIds.value = rows.map((row) => row.id);
}

async function batch(action: "enable" | "disable" | "delete") {
  if (!selectedIds.value.length) return;
  const label = action === "enable" ? "启用" : action === "disable" ? "禁用" : "删除";
  try {
    await ElMessageBox.confirm(`确定批量${label} ${selectedIds.value.length} 个用户吗？`, "批量操作", {
      type: action === "delete" ? "error" : "warning",
    });
  } catch {
    return;
  }
  try {
    const result = await api.post<any>("/auth/users/batch/", {
      action,
      user_ids: selectedIds.value,
    });
    const extra = result?.errors?.length ? `，${result.errors.length} 个失败` : "";
    ElMessage.success(`已${label} ${result?.updated || 0} 个用户${extra}`);
    selectedIds.value = [];
    await load();
  } catch (error: any) {
    ElMessage.error(error?.message || "批量操作失败");
  }
}

function openInvite() {
  inviteResult.value = null;
  inviteForm.username = "";
  inviteForm.email = "";
  inviteForm.first_name = "";
  inviteVisible.value = true;
}

async function createInvite() {
  if (!inviteForm.username.trim()) {
    ElMessage.warning("请输入用户名");
    return;
  }
  inviteSaving.value = true;
  try {
    inviteResult.value = await api.post<any>("/auth/users/", {
      username: inviteForm.username.trim(),
      email: inviteForm.email.trim(),
      first_name: inviteForm.first_name.trim(),
    });
    await load();
  } catch (error: any) {
    ElMessage.error(error?.message || "创建邀请失败");
  } finally {
    inviteSaving.value = false;
  }
}

async function copyPassword() {
  try {
    await navigator.clipboard.writeText(inviteResult.value?.temporary_password || "");
    ElMessage.success("临时密码已复制");
  } catch {
    ElMessage.warning("复制失败，请手动选择");
  }
}

function openEdit(row: UserInfo) {
  target.value = row;  form.first_name = row.first_name || "";
  form.last_name = row.last_name || "";
  form.email = row.email || "";
  form.is_superuser = row.is_superuser;
  editVisible.value = true;
}

async function save() {
  if (!target.value) return;
  saving.value = true;
  try {
    await api.put(`/auth/users/${target.value.id}/`, {
      username: target.value.username,
      first_name: form.first_name || null,
      last_name: form.last_name || null,
      email: form.email || null,
      is_superuser: form.is_superuser,
    });
    ElMessage.success("已保存");
    editVisible.value = false;
    load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "保存失败");
  } finally {
    saving.value = false;
  }
}

async function toggleSuperuser(row: UserInfo, v: boolean) {
  switchingId.value = row.id;
  try {
    await api.put(`/auth/users/${row.id}/`, { username: row.username, is_superuser: v });
    row.is_superuser = v;
    ElMessage.success(v ? "已授予超级管理员" : "已取消超级管理员");
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "操作失败");
  } finally {
    switchingId.value = null;
  }
}

async function toggleActive(row: UserInfo) {
  const dis = row.is_active;
  try {
    await ElMessageBox.confirm(
      dis ? `确定禁用用户「${row.username}」吗？禁用后该用户无法登录。` : `确定重新启用用户「${row.username}」吗？`,
      "提示",
      { type: "warning" }
    );
  } catch {
    return;
  }
  try {
    await api.put(`/auth/users/${row.id}/`, { username: row.username, is_active: !dis });
    row.is_active = !dis;
    ElMessage.success(dis ? "已禁用" : "已启用");
    load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "操作失败");
  }
}

async function deleteUser(row: UserInfo) {
  try {
    await ElMessageBox.prompt(
      `删除后不可恢复。请输入用户名「${row.username}」确认：`,
      "删除用户",
      {
        type: "warning",
        inputPlaceholder: row.username,
        inputValidator: (value: string) => value === row.username || "用户名不一致",
        confirmButtonText: "删除",
        cancelButtonText: "取消",
        confirmButtonClass: "el-button--danger",
      }
    );
  } catch {
    return;
  }
  try {
    await api.del(`/auth/users/${row.id}/`);
    ElMessage.success(`已删除用户「${row.username}」`);
    if (users.value.length === 1 && page.value > 1) page.value -= 1;
    load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "删除失败");
  }
}

onMounted(load);
</script>

<style scoped>
.wp-page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.wp-page-header h2 {  margin: 0;
  font-size: 18px;
}
.wp-filter-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.wp-batch-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  padding: 8px 12px;
  border: 1px solid var(--el-color-warning-light-7);
  border-radius: 6px;
  background: var(--el-color-warning-light-9);
  font-size: 13px;
}
.wp-pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>
