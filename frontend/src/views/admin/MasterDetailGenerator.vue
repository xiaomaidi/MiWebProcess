<template>
  <el-dialog v-model="visible" title="生成主子表页面" width="620px" @close="reset">
    <el-alert
      title="自动生成列表页 + 详情页：主表可查询，详情页编辑主表并维护子表明细。"
      type="info"
      :closable="false"
      show-icon
      class="wp-gen-alert"
    />
    <el-form label-position="top">
      <el-form-item label="主模型">
        <el-select v-model="masterId" filterable style="width: 100%" @change="syncChild">
          <el-option v-for="m in models" :key="m.id" :label="`${m.name} (#${m.id})`" :value="m.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="子模型">
        <el-select v-model="childId" filterable style="width: 100%">
          <el-option v-for="m in models" :key="m.id" :label="`${m.name} (#${m.id})`" :value="m.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="子表外键字段">
        <el-select v-model="foreignKey" filterable allow-create style="width: 100%" placeholder="例如 order_id">
          <el-option v-for="f in childFields" :key="f.name" :label="`${f.label || f.name} (${f.name})`" :value="f.name" />
        </el-select>
      </el-form-item>
      <el-form-item label="页面路径前缀">
        <el-input v-model="pathPrefix" placeholder="例如 erp/orders" />
      </el-form-item>
      <el-form-item label="页面名称">
        <el-input v-model="pageTitle" placeholder="例如 采购订单" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="loading" @click="generate">生成页面</el-button>
    </template>
    <el-dialog v-model="doneVisible" title="生成完成" width="420px" append-to-body>
      <p>已生成并发布：</p>
      <p><a :href="listUrl" target="_blank">{{ listUrl }}</a></p>
      <p><a :href="detailUrl" target="_blank">{{ detailUrl }}</a></p>
      <template #footer><el-button type="primary" @click="doneVisible = false">知道了</el-button></template>
    </el-dialog>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { api } from "@/api";
import type { DataModelField, DataModelInfo } from "@/types";

const props = defineProps<{
  modelValue: boolean;
  appId: number;
  models: DataModelInfo[];
  defaultMasterId?: number;
}>();
const emit = defineEmits<{
  (e: "update:modelValue", v: boolean): void;
  (e: "generated", payload: { listId: number; detailId: number }): void;
}>();

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit("update:modelValue", v),
});
const masterId = ref(0);
const childId = ref(0);
const foreignKey = ref("");
const pathPrefix = ref("");
const pageTitle = ref("");
const loading = ref(false);
const doneVisible = ref(false);
const listUrl = ref("");
const detailUrl = ref("");

const master = computed(() => props.models.find((m) => m.id === masterId.value));
const child = computed(() => props.models.find((m) => m.id === childId.value));
const childFields = computed<DataModelField[]>(() => child.value?.fields || []);

function suggestPair() {
  // 1) 优先使用 reference 字段的显式关系。
  for (const child of props.models) {
    for (const field of child.fields || []) {
      if (field.type !== "reference" || !field.ref_model) continue;
      const master = props.models.find((m) => m.name === field.ref_model && m.id !== child.id);
      if (master) return { master, child, foreignKey: field.name };
    }
  }
  // 2) 兼容常见的 <master>_id 数字外键：erp_order + erp_order_item.order_id。
  for (const master of props.models) {
    const base = master.name.split("_").pop();
    for (const child of props.models) {
      if (child.id === master.id) continue;
      const field = (child.fields || []).find(
        (f) => f.name === `${base}_id` || f.name === `${master.name}_id`
      );
      if (field) return { master, child, foreignKey: field.name };
    }
  }
  const master = props.models[0];
  const child = props.models.find((m) => m.id !== master?.id);
  return master && child ? { master, child, foreignKey: "" } : null;
}

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return;
    const pair = suggestPair();
    masterId.value = props.defaultMasterId || pair?.master.id || props.models[0]?.id || 0;
    childId.value = pair?.child.id || props.models.find((m) => m.id !== masterId.value)?.id || 0;
    foreignKey.value = pair?.foreignKey || "";
    pathPrefix.value = "";
    pageTitle.value = "";
    syncChild();
  }
);

function syncChild() {
  if (!pathPrefix.value && master.value) pathPrefix.value = `pages/model-${master.value.id}`;
  if (!pageTitle.value && master.value) pageTitle.value = master.value.name;
  if (!foreignKey.value) {
    const f = childFields.value.find((x) => /(_id|id)$/i.test(x.name) && x.name !== "id");
    foreignKey.value = f?.name || "";
  }
}

function fieldColumns(fields: DataModelField[]) {
  return fields.map((f) => ({
    key: f.name,
    prop: f.name,
    label: f.label || f.name,
    minWidth: f.type === "json" ? 200 : 110,
    cellType: f.type === "boolean" ? "tag" : "text",
    ...(f.type === "boolean" ? { valueMap: { true: "是", false: "否" }, tagType: "success" } : {}),
  }));
}

function node(id: string, type: string, props: Record<string, any> = {}, children: string[] = [], style?: Record<string, any>) {
  return { id, type, componentVersion: "2.0.0", props, children, ...(style ? { style } : {}) };
}

function schema(nodes: Record<string, any>, title: string) {
  return {
    schemaVersion: 2,
    rootId: "root",
    nodes,
    layout: { mode: "flow", width: 1200, height: 900 },
    variables: {},
    meta: { title, lang: "zh-CN", seo: { description: title } },
  };
}

async function createPage(name: string, path: string, pageSchema: any) {
  const page = await api.post<any>(`/apps/${props.appId}/pages/`, { name, path, type: "page" });
  await api.put(`/pages/${page.id}/schema/`, { schema: pageSchema });
  await api.post(`/pages/${page.id}/publish/`, { changelog: "master-detail generator" });
  return page;
}

async function generate() {
  if (!master.value || !child.value) {
    ElMessage.warning("请选择主模型和子模型");
    return;
  }
  if (!foreignKey.value || !childFields.value.some((f) => f.name === foreignKey.value)) {
    ElMessage.warning("请选择子表中存在的外键字段");
    return;
  }
  const prefix = pathPrefix.value.trim().replace(/^\/+|\/+$/g, "");
  if (!prefix || !pageTitle.value.trim()) {
    ElMessage.warning("请填写页面路径前缀和名称");
    return;
  }
  loading.value = true;
  try {
    const listCols = [
      ...fieldColumns(master.value.fields || []),
      {
        key: "_actions",
        label: "操作",
        width: 90,
        cellType: "button",
        buttonText: "查看",
        navigatePattern: `${prefix}/{id}`,
      },
    ];
    const listNodes = {
      root: node("root", "wp-canvas", {}, ["main"]),
      main: node("main", "ElContainer", { direction: "vertical", padding: 24, background: "#f5f7fa" }, ["title", "table"]),
      title: node("title", "ElText", { text: pageTitle.value, size: "large", tag: "h2" }, [], { fontSize: "24px", fontWeight: "700", margin: "0 0 16px" }),
      table: node("table", "ElTable", {
        dataModelId: master.value.id,
        remote: true,
        showPagination: true,
        pageSize: 10,
        showSearch: true,
        exportable: true,
        rowKey: "id",
        columns: listCols,
      }),
    };
    const list = await createPage(`${pageTitle.value}列表`, prefix, schema(listNodes, `${pageTitle.value}列表`));

    const detailNodes = {
      root: node("root", "wp-canvas", {}, ["main"]),
      main: node("main", "ElContainer", { direction: "vertical", padding: 24, background: "#f5f7fa" }, ["masterCard", "childCard"]),
      masterCard: node("masterCard", "ElCard", { title: pageTitle.value, shadow: "never", padding: 20 }, ["form"]),
      form: node("form", "auto-form", {
        modelId: master.value.id,
        mode: "edit",
        recordId: "{{route.id}}",
        fieldColumns: 2,
        labelPosition: "top",
        submitText: "保存",
        showReset: false,
        successMessage: "主表已保存",
      }),
      childCard: node("childCard", "ElCard", { title: "明细", shadow: "never", padding: 20 }, ["items"], { marginTop: "16px" }),
      items: node("items", "relation-table", {
        modelId: child.value.id,
        foreignKey: foreignKey.value,
        parentId: "{{route.id}}",
        columns: fieldColumns(child.value.fields || []),
        addText: "新增明细",
      }),
    };
    const detail = await createPage(`${pageTitle.value}详情`, `${prefix}/:id`, schema(detailNodes, `${pageTitle.value}详情`));
    await api.post(`/apps/${props.appId}/releases/`, { changelog: "master-detail generator" });
    const origin = window.location.origin;
    listUrl.value = `${origin}/run/${(await api.get<any>(`/apps/${props.appId}`)).code}/${prefix}`;
    detailUrl.value = `${origin}/run/${(await api.get<any>(`/apps/${props.appId}`)).code}/${prefix}/:id`;
    doneVisible.value = true;
    emit("generated", { listId: list.id, detailId: detail.id });
    ElMessage.success("主子表页面已生成并发布");
  } catch (e: any) {
    ElMessage.error(e?.message || "生成失败，请检查路径是否已存在");
  } finally {
    loading.value = false;
  }
}

function reset() {
  foreignKey.value = "";
  pathPrefix.value = "";
  pageTitle.value = "";
}
</script>

<style scoped>
.wp-gen-alert {
  margin-bottom: 14px;
}
</style>
