<template>
  <el-drawer v-model="open" :title="`权限 · ${user?.username || ''}`" size="760px">
    <div v-loading="loading" class="wp-access">
      <div class="wp-access-platform">
        <span class="wp-access-label">平台权限</span>
        <el-tag size="small" :type="access?.platform?.is_superuser ? 'danger' : 'info'" effect="plain">
          {{ access?.platform?.is_superuser ? "超级管理员" : access?.platform?.is_platform_admin ? "平台管理员" : "普通用户" }}
        </el-tag>
        <el-switch
          :model-value="access?.platform?.is_platform_admin || false"
          :disabled="isSelf"
          active-text="平台管理员"
          @change="(v: boolean) => setPlatform('is_platform_admin', v)"
        />
        <el-switch
          :model-value="access?.platform?.is_superuser || false"
          :disabled="isSelf"
          active-text="超级管理员"
          @change="(v: boolean) => setPlatform('is_superuser', v)"
        />
        <el-switch
          :model-value="access?.platform?.is_active ?? true"
          :disabled="isSelf"
          active-text="启用"
          @change="(v: boolean) => setPlatform('is_active', v)"
        />
        <el-button size="small" @click="resetPassword">重置密码</el-button>
      </div>

      <div class="wp-access-section">
        <div class="wp-access-head">
          <strong>应用权限</strong>
          <span>角色：owner 管理全部，editor 编辑页面和数据，viewer 只读</span>
        </div>
        <el-table :data="access?.apps || []" size="small" border>
          <el-table-column prop="name" label="应用" min-width="150" />
          <el-table-column prop="code" label="编码" min-width="140" />
          <el-table-column label="角色" width="150">
            <template #default="{ row }">
              <el-select
                v-if="!row.is_owner"
                :model-value="row.role"
                size="small"
                @change="(v: string) => updateAppRole(row, v)"
              >
                <el-option label="只读 viewer" value="viewer" />
                <el-option label="编辑 editor" value="editor" />
              </el-select>
              <el-tag v-else size="small" type="warning">所有者</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="80">
            <template #default="{ row }">
              <el-button v-if="!row.is_owner" size="small" type="danger" plain @click="removeApp(row)">移除</el-button>
            </template>
          </el-table-column>
          <template #empty><el-empty description="没有任何应用权限" :image-size="50" /></template>
        </el-table>
        <div class="wp-access-add">
          <el-select v-model="newAppId" size="small" placeholder="选择应用" filterable style="width: 220px">
            <el-option v-for="app in appOptions" :key="app.id" :label="`${app.name} (${app.code})`" :value="app.id" />
          </el-select>
          <el-select v-model="newAppRole" size="small" style="width: 120px">
            <el-option label="只读" value="viewer" />
            <el-option label="编辑" value="editor" />
          </el-select>
          <el-button size="small" type="primary" :disabled="!newAppId" @click="addApp">添加应用权限</el-button>
        </div>
      </div>

      <div class="wp-access-section">
        <div class="wp-access-head">
          <strong>部门</strong>
          <span>部门负责人可以看到子部门数据</span>
        </div>
        <div class="wp-access-chips">
          <el-tag v-for="dept in access?.departments || []" :key="dept.id" size="small" closable @close="removeDept(dept)">
            {{ dept.name }} · {{ dept.role }}
          </el-tag>
          <span v-if="!(access?.departments || []).length" class="wp-access-muted">未加入部门</span>
        </div>
        <div class="wp-access-add">
          <el-select v-model="newDepartmentId" size="small" placeholder="选择部门" filterable style="width: 220px">
            <el-option v-for="dept in departmentOptions" :key="dept.id" :label="dept.label" :value="dept.id" />
          </el-select>
          <el-button size="small" type="primary" :disabled="!newDepartmentId" @click="addDept">加入部门</el-button>
        </div>
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { api } from "@/api";
import { useAuthStore } from "@/store/auth";
import type { UserInfo } from "@/types";

const props = defineProps<{ modelValue: boolean; user: UserInfo | null }>();
const emit = defineEmits<{ "update:modelValue": [value: boolean]; changed: [] }>();

const auth = useAuthStore();
const loading = ref(false);
const access = ref<any>(null);
const allApps = ref<any[]>([]);
const departments = ref<any[]>([]);
const newAppId = ref<number | null>(null);
const newAppRole = ref("viewer");
const newDepartmentId = ref<number | null>(null);

const open = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit("update:modelValue", value),
});
const isSelf = computed(() => props.user?.id === auth.user?.id);

const appOptions = computed(() => {
  const assigned = new Set((access.value?.apps || []).map((item: any) => item.id));
  return allApps.value.filter((app) => !assigned.has(app.id));
});
const departmentOptions = computed(() => {
  const joined = new Set((access.value?.departments || []).map((item: any) => item.id));
  return departments.value.filter((dept) => !joined.has(dept.id));
});

function asList(data: any): any[] {
  if (Array.isArray(data)) return data;
  return Array.isArray(data?.results) ? data.results : [];
}

async function load() {
  if (!props.user) return;
  loading.value = true;
  try {
    const [accessRes, appsRes, treeRes] = await Promise.all([
      api.get<any>(`/auth/users/${props.user.id}/access/`),
      api.get<any>("/apps/?scope=all&size=100"),
      api.get<any>("/org/tree/"),
    ]);
    access.value = accessRes;
    allApps.value = asList(appsRes);
    departments.value = (treeRes?.nodes || []).map((node: any) => ({
      id: node.id,
      label: node.name,
    }));
    newAppId.value = null;
    newDepartmentId.value = null;
  } catch (error: any) {
    ElMessage.error(error?.message || "加载用户权限失败");
  } finally {
    loading.value = false;
  }
}

async function setPlatform(key: string, value: boolean) {
  if (!props.user) return;
  try {
    await api.patch(`/auth/users/${props.user.id}/`, { [key]: value });
    ElMessage.success("平台权限已更新");
    emit("changed");
    await load();
  } catch (error: any) {
    ElMessage.error(error?.message || "更新失败");
  }
}

async function resetPassword() {
  if (!props.user) return;
  let password = "";
  try {
    const result = await ElMessageBox.prompt(
      `为用户「${props.user.username}」设置新密码：`,
      "重置密码",
      {
        inputType: "password",
        inputPlaceholder: "至少 8 位",
        inputValidator: (value: string) => (value?.length >= 8 ? true : "密码至少 8 位"),
        confirmButtonText: "重置",
        cancelButtonText: "取消",
      }
    );
    password = String(result.value || "");
  } catch {
    return;
  }
  try {
    await api.post(`/auth/users/${props.user.id}/reset-password/`, { password });
    ElMessage.success("密码已重置");
  } catch (error: any) {
    ElMessage.error(error?.message || "重置失败");
  }
}

async function addApp() {
  if (!props.user || !newAppId.value) return;
  try {
    await api.post(`/apps/${newAppId.value}/members/`, {
      user_id: props.user.id,
      role: newAppRole.value,
    });
    ElMessage.success("已添加应用权限");
    emit("changed");
    await load();
  } catch (error: any) {
    ElMessage.error(error?.message || "添加失败");
  }
}

async function updateAppRole(row: any, role: string) {
  if (!props.user) return;
  try {
    await api.put(`/apps/${row.id}/members/${props.user.id}/`, { role });
    row.role = role;
    ElMessage.success("角色已更新");
    emit("changed");
  } catch (error: any) {
    ElMessage.error(error?.message || "更新失败");
    await load();
  }
}

async function removeApp(row: any) {
  if (!props.user) return;
  try {
    await ElMessageBox.confirm(`移除「${row.name}」的应用权限？`, "确认", { type: "warning" });
    await api.del(`/apps/${row.id}/members/${props.user.id}/`);
    ElMessage.success("已移除");
    emit("changed");
    await load();
  } catch {
    /* 取消或失败已提示 */
  }
}

async function addDept() {
  if (!props.user || !newDepartmentId.value) return;
  try {
    await api.post(`/org/departments/${newDepartmentId.value}/members/`, {
      user_id: props.user.id,
      role: "member",
    });
    ElMessage.success("已加入部门");
    emit("changed");
    await load();
  } catch (error: any) {
    ElMessage.error(error?.message || "加入失败");
  }
}

async function removeDept(dept: any) {
  if (!props.user) return;
  try {
    await api.del(`/org/departments/${dept.id}/members/${props.user.id}/`);
    ElMessage.success("已移出部门");
    emit("changed");
    await load();
  } catch (error: any) {
    ElMessage.error(error?.message || "移除失败");
  }
}

watch(
  () => props.modelValue,
  (visible) => {
    if (visible) load();
  }
);
</script>

<style scoped>
.wp-access {
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.wp-access-platform {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.wp-access-label {
  font-weight: 600;
}
.wp-access-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.wp-access-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.wp-access-head span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.wp-access-add {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.wp-access-chips {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.wp-access-muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
