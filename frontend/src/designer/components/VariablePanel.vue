<template>
  <div class="wp-var-panel">
    <div class="wp-var-toolbar">
      <el-button size="small" type="primary" @click="openCreate">新建变量</el-button>
    </div>
    <el-empty v-if="!rows.length" description="暂无应用变量" :image-size="60" />
    <div v-for="r in rows" :key="r.key" class="wp-var-row">
      <div class="wp-var-main">
        <span class="wp-var-key" :title="r.key">{{ r.key }}</span>
        <span class="wp-var-value" :title="preview(r.value)">{{ preview(r.value) }}</span>
      </div>
      <div class="wp-var-ops">
        <el-button size="small" @click="openEdit(r.key)">编辑</el-button>
        <el-button size="small" type="danger" @click="onDelete(r.key)">删除</el-button>
      </div>
    </div>

    <el-dialog v-model="dialogOpen" :title="editingKey ? `编辑变量：${editingKey}` : '新建变量'" width="480px">
      <el-form label-position="top">
        <el-form-item label="变量名 key">
          <el-input v-model="form.key" :disabled="!!editingKey" placeholder="例如：currentUser" />
        </el-form-item>
        <el-form-item label="值（JSON）">
          <el-input v-model="form.value" type="textarea" :rows="5" placeholder='例如：{"id":1,"name":"张三"} 或 "文本" 或 123' />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" @click="onSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { useSchemaStore } from "@/store/schema";
import { parseJson, prettyJson, withHistory } from "../util";

const schema = useSchemaStore();

const rows = computed(() =>
  Object.entries(schema.schema?.variables ?? {}).map(([key, v]) => {
    const def = (v ?? {}) as { value?: any; scope?: string };
    return { key, value: def.value, scope: def.scope };
  })
);

const dialogOpen = ref(false);
const editingKey = ref<string | null>(null);
const form = reactive({ key: "", value: "", scope: "global" as "global" | "page" });

function preview(v: unknown): string {
  const s = typeof v === "string" ? v : prettyJson(v);
  return s.length > 40 ? s.slice(0, 40) + "…" : s;
}

function openCreate() {
  editingKey.value = null;
  form.key = "";
  form.value = "";
  form.scope = "global";
  dialogOpen.value = true;
}

function openEdit(key: string) {
  editingKey.value = key;
  form.key = key;
  const def = (schema.schema?.variables?.[key] ?? {}) as { value?: any; scope?: string };
  form.value = prettyJson(def.value ?? null);
  form.scope = def.scope === "page" ? "page" : "global";
  dialogOpen.value = true;
}

function onSave() {
  const key = form.key.trim();
  if (!key || !/^[A-Za-z_$][\w$]*$/.test(key)) {
    ElMessage.warning("变量名需为合法标识符");
    return;
  }
  // 值可为任意 JSON；纯文本直接作为字符串字面量
  const value = parseJson(form.value) ?? form.value;
  const scope = form.scope;
  withHistory("编辑变量", () => {
    schema.addVariable(key, { value, scope: scope || undefined });
  });
  dialogOpen.value = false;
  ElMessage.success("变量已保存（记得保存页面）");
}

function onDelete(key: string) {
  withHistory("删除变量", () => {
    schema.removeVariable(key);
  });
  ElMessage.success("变量已删除（记得保存页面）");
}
</script>

<style scoped>
.wp-var-panel {
  padding: 8px;
  font-size: 13px;
}
.wp-var-toolbar {
  margin-bottom: 8px;
}
.wp-var-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 8px;
  margin-bottom: 6px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  background: #fff;
}
.wp-var-main {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1;
}
.wp-var-key {
  font-weight: 600;
  flex: none;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wp-var-value {
  color: #909399;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wp-var-ops {
  display: flex;
  gap: 4px;
  flex: none;
}
</style>
