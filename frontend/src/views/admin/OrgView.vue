<template>
  <div class="wp-admin-page" v-loading="loading">
    <div class="wp-page-header">
      <div class="wp-page-title-block">
        <h2>组织架构</h2>
        <p class="wp-page-desc">部门树支持无限层级；负责人可见整棵子树的数据，成员仅本部门。应用开启“部门可见”后，部门成员获得只读访问。</p>
      </div>
      <div class="wp-page-actions">
        <el-button v-if="isAdmin" type="primary" @click="openCreate(null)">新建根部门</el-button>
        <el-button @click="loadAll">刷新</el-button>
      </div>
    </div>

    <el-row :gutter="16">
      <el-col :span="8">
        <el-card shadow="never" class="wp-org-tree-card">
          <template #header>
            <div class="wp-card-header">
              <span>部门树</span>
              <el-tag size="small" type="info" effect="plain">{{ nodes.length }} 个部门</el-tag>
            </div>
          </template>
          <el-tree
            :data="tree"
            node-key="id"
            :props="{ label: 'name', children: 'children' }"
            default-expand-all
            highlight-current
            :expand-on-click-node="false"
            @node-click="selectDepartment"
          >
            <template #default="{ data }">
              <span class="wp-org-node">
                <span class="wp-org-node-name">{{ data.name }}</span>
                <el-tag v-if="data.leader_name" size="small" effect="plain">{{ data.leader_name }}</el-tag>
                <el-tag size="small" type="info" effect="plain">{{ data.member_count || 0 }} 人</el-tag>
              </span>
            </template>
          </el-tree>
          <el-empty v-if="!tree.length" description="还没有部门" :image-size="60" />
        </el-card>
      </el-col>

      <el-col :span="16">
        <el-card shadow="never" v-if="current">
          <template #header>
            <div class="wp-card-header">
              <span>
                {{ current.name }}
                <el-tag size="small" effect="plain">{{ current.display_path }}</el-tag>
              </span>
              <span class="wp-card-actions">
                <el-button size="small" v-if="canManage(current)" @click="openCreate(current)">新建子部门</el-button>
                <el-button size="small" v-if="canManage(current)" @click="openMove(current)">移动</el-button>
                <el-button size="small" v-if="canManage(current)" @click="openEdit(current)">编辑</el-button>
                <el-button size="small" type="danger" plain v-if="canManage(current)" @click="removeDepartment(current)">删除</el-button>
              </span>
            </div>
          </template>

          <el-descriptions :column="3" border size="small">
            <el-descriptions-item label="部门编码">{{ current.code || "—" }}</el-descriptions-item>
            <el-descriptions-item label="层级">{{ current.level + 1 }}</el-descriptions-item>
            <el-descriptions-item label="负责人">{{ current.leader_name || "未设置" }}</el-descriptions-item>
            <el-descriptions-item label="成员数">{{ members.length }}</el-descriptions-item>
            <el-descriptions-item label="状态">
              <el-tag size="small" :type="current.is_active ? 'success' : 'info'">{{ current.is_active ? "启用" : "停用" }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="创建时间">{{ formatTime(current.created_at) }}</el-descriptions-item>
          </el-descriptions>

          <div class="wp-tab-toolbar" style="margin-top: 16px">
            <el-button type="primary" size="small" v-if="canManage(current)" @click="openMemberAdd">添加成员</el-button>
            <el-button size="small" @click="loadMembers">刷新</el-button>
          </div>
          <el-table :data="members" border stripe size="small">
            <el-table-column label="成员" min-width="160">
              <template #default="{ row }">
                {{ row.display_name }}
                <span class="wp-muted">@{{ row.username }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="title" label="职位" width="140" />
            <el-table-column label="角色" width="110">
              <template #default="{ row }">
                <el-tag size="small" :type="row.role === 'leader' ? 'danger' : 'info'">
                  {{ row.role === "leader" ? "负责人" : "成员" }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="150" v-if="canManage(current)">
              <template #default="{ row }">
                <el-button size="small" @click="toggleRole(row)">{{ row.role === "leader" ? "设为成员" : "设为负责人" }}</el-button>
                <el-button size="small" type="danger" plain @click="removeMember(row)">移除</el-button>
              </template>
            </el-table-column>
            <template #empty><el-empty description="暂无成员" :image-size="50" /></template>
          </el-table>
        </el-card>
        <el-card shadow="never" v-else>
          <el-empty description="从左侧选择一个部门" :image-size="80" />
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="dlg.department" :title="editing ? '编辑部门' : '新建部门'" width="520px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="名称" required><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="编码"><el-input v-model="form.code" placeholder="可选，如 EAST" /></el-form-item>
        <el-form-item label="上级部门">
          <el-select v-model="form.parent_id" clearable style="width: 100%">
            <el-option v-for="node in nodes" :key="node.id" :label="node.display_path" :value="node.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="负责人">
          <el-select v-model="form.leader_id" clearable filterable style="width: 100%">
            <el-option v-for="user in users" :key="user.id" :label="`${user.display_name} @${user.username}`" :value="user.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="排序"><el-input-number v-model="form.sort" :min="0" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="form.description" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg.department = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveDepartment">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="dlg.move" title="移动部门" width="460px">
      <el-form label-width="90px">
        <el-form-item label="目标上级">
          <el-select v-model="moveTarget" clearable placeholder="移动到根部门" style="width: 100%">
            <el-option
              v-for="node in movableTargets"
              :key="node.id"
              :label="node.display_path"
              :value="node.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg.move = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveMove">移动</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="dlg.member" title="添加部门成员" width="460px">
      <el-form label-width="70px">
        <el-form-item label="用户">
          <el-select v-model="memberForm.user_id" filterable remote :remote-method="searchUsers" style="width: 100%">
            <el-option v-for="user in users" :key="user.id" :label="`${user.display_name} @${user.username}`" :value="user.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="角色">
          <el-radio-group v-model="memberForm.role">
            <el-radio value="member">成员</el-radio>
            <el-radio value="leader">负责人</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="职位"><el-input v-model="memberForm.title" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg.member = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="addMember">添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { api } from "@/api";
import { formatTime } from "@/utils";
import { useAuthStore } from "@/store/auth";

interface DepartmentNode {
  id: number;
  name: string;
  code: string;
  parent_id: number | null;
  path: string;
  level: number;
  sort: number;
  leader_id: number | null;
  leader_name: string;
  description: string;
  is_active: boolean;
  member_count?: number;
  display_path: string;
  created_at: string;
}

interface OrgUser {
  id: number;
  username: string;
  display_name: string;
}

const auth = useAuthStore();
const loading = ref(false);
const saving = ref(false);
const nodes = ref<DepartmentNode[]>([]);
const current = ref<DepartmentNode | null>(null);
const members = ref<any[]>([]);
const users = ref<OrgUser[]>([]);
const managedIds = ref<number[]>([]);
const isAdmin = computed(() => !!auth.user?.is_superuser);

const dlg = reactive({ department: false, move: false, member: false });
const editing = ref(false);
const form = reactive<Record<string, any>>({ name: "", code: "", parent_id: null, leader_id: null, sort: 0, description: "" });
const moveTarget = ref<number | null>(null);
const memberForm = reactive<{ user_id: number | null; role: string; title: string }>({ user_id: null, role: "member", title: "" });

const tree = computed(() => {
  const byId = new Map<number, any>();
  const roots: any[] = [];
  for (const node of nodes.value) byId.set(node.id, { ...node, children: [] });
  for (const node of nodes.value) {
    const item = byId.get(node.id);
    if (node.parent_id && byId.has(node.parent_id)) byId.get(node.parent_id)!.children.push(item);
    else roots.push(item);
  }
  return roots;
});

const movableTargets = computed(() => {
  if (!current.value) return [];
  const prefix = current.value.path || "";
  return nodes.value.filter((n) => n.id !== current.value!.id && !(prefix && n.path.startsWith(prefix)));
});

function canManage(node: DepartmentNode | null): boolean {
  if (!node) return false;
  return isAdmin.value || managedIds.value.includes(node.id);
}

async function loadAll() {
  loading.value = true;
  try {
    const [list, me] = await Promise.all([
      api.get<{ results: DepartmentNode[] }>("/org/departments/?size=100"),
      api.get<{ managed_department_ids: number[] }>("/org/me/"),
    ]);
    nodes.value = list.results || [];
    managedIds.value = me.managed_department_ids || [];
    if (!current.value && nodes.value.length) selectDepartment(nodes.value[0]);
    else if (current.value) {
      const fresh = nodes.value.find((n) => n.id === current.value!.id);
      current.value = fresh || nodes.value[0] || null;
      if (current.value) await loadMembers();
    }
  } finally {
    loading.value = false;
  }
}

async function selectDepartment(node: DepartmentNode) {
  current.value = node;
  await Promise.all([loadMembers(), loadUsers()]);
}

async function loadMembers() {
  if (!current.value) return;
  const res = await api.get<{ results: any[] }>(`/org/departments/${current.value.id}/members/?size=100`);
  members.value = res.results || [];
}

async function loadUsers(q = "") {
  try {
    const res = await api.get<{ results: OrgUser[] }>(`/org/users/?q=${encodeURIComponent(q)}`);
    users.value = res.results || [];
  } catch {
    users.value = [];
  }
}

function searchUsers(q: string) {
  loadUsers(q);
}

function openCreate(parent: DepartmentNode | null) {
  editing.value = false;
  Object.assign(form, { name: "", code: "", parent_id: parent?.id ?? null, leader_id: null, sort: 0, description: "" });
  dlg.department = true;
  loadUsers();
}

function openEdit(node: DepartmentNode) {
  editing.value = true;
  Object.assign(form, {
    name: node.name,
    code: node.code,
    parent_id: node.parent_id,
    leader_id: node.leader_id,
    sort: node.sort,
    description: node.description,
    id: node.id,
  });
  dlg.department = true;
  loadUsers();
}

async function saveDepartment() {
  if (!form.name?.trim()) {
    ElMessage.warning("请填写部门名称");
    return;
  }
  saving.value = true;
  try {
    if (editing.value) {
      await api.patch(`/org/departments/${form.id}/`, {
        name: form.name,
        code: form.code,
        leader_id: form.leader_id || null,
        sort: form.sort,
        description: form.description,
      });
      if (form.parent_id !== current.value?.parent_id) {
        await api.post(`/org/departments/${form.id}/move/`, { parent_id: form.parent_id || null });
      }
    } else {
      await api.post("/org/departments/", {
        name: form.name,
        code: form.code,
        parent_id: form.parent_id || null,
        leader_id: form.leader_id || null,
        sort: form.sort,
        description: form.description,
      });
    }
    ElMessage.success("已保存");
    dlg.department = false;
    await loadAll();
  } finally {
    saving.value = false;
  }
}

function openMove(node: DepartmentNode) {
  current.value = node;
  moveTarget.value = node.parent_id;
  dlg.move = true;
}

async function saveMove() {
  if (!current.value) return;
  saving.value = true;
  try {
    await api.post(`/org/departments/${current.value.id}/move/`, { parent_id: moveTarget.value || null });
    ElMessage.success("已移动");
    dlg.move = false;
    await loadAll();
  } finally {
    saving.value = false;
  }
}

async function removeDepartment(node: DepartmentNode) {
  try {
    await ElMessageBox.confirm(`删除“${node.name}”会同时删除其子部门，确定继续？`, "删除部门", { type: "warning" });
  } catch {
    return;
  }
  await api.del(`/org/departments/${node.id}/`);
  ElMessage.success("已删除");
  current.value = null;
  await loadAll();
}

function openMemberAdd() {
  Object.assign(memberForm, { user_id: null, role: "member", title: "" });
  dlg.member = true;
  loadUsers();
}

async function addMember() {
  if (!current.value || !memberForm.user_id) {
    ElMessage.warning("请选择用户");
    return;
  }
  saving.value = true;
  try {
    await api.post(`/org/departments/${current.value.id}/members/`, memberForm);
    ElMessage.success("已添加");
    dlg.member = false;
    await loadMembers();
  } finally {
    saving.value = false;
  }
}

async function toggleRole(row: any) {
  const role = row.role === "leader" ? "member" : "leader";
  await api.patch(`/org/departments/${current.value!.id}/members/${row.user_id}/`, { role });
  await loadMembers();
}

async function removeMember(row: any) {
  await api.del(`/org/departments/${current.value!.id}/members/${row.user_id}/`);
  await loadMembers();
}

onMounted(loadAll);
</script>

<style scoped>
.wp-org-tree-card :deep(.el-card__body) {
  min-height: 420px;
}
.wp-org-node {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.wp-org-node-name {
  font-weight: 500;
}
.wp-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.wp-card-actions {
  display: inline-flex;
  gap: 4px;
}
.wp-muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-left: 4px;
}
</style>
