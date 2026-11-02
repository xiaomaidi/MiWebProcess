<template>
  <div class="wp-style">
    <el-empty v-if="!node" description="节点不存在" :image-size="50" />
    <template v-else>
      <el-collapse v-model="open" class="wp-style-collapse">
        <el-collapse-item v-for="section in SECTIONS" :key="section.key" :title="section.title" :name="section.key">
          <div v-for="[k, label, placeholder] in section.fields" :key="k" class="wp-style-row">
            <label>{{ label }}</label>
            <el-select
              v-if="section.key === 'typography' && (k === 'textAlign' || k === 'textDecoration' || k === 'whiteSpace')"
              v-model="form[k]"
              size="small"
              clearable
              placeholder="auto"
              @change="setField(k, form[k])"
            >
              <el-option v-for="o in alignOptions(k)" :key="o" :label="o" :value="o" />
            </el-select>
            <el-select
              v-else-if="section.key === 'layout' && (k === 'display' || k === 'position' || k === 'flexDirection' || k === 'flexWrap' || k === 'alignItems' || k === 'justifyContent')"
              v-model="form[k]"
              size="small"
              clearable
              placeholder="auto"
              @change="setField(k, form[k])"
            >
              <el-option v-for="o in layoutOptions(k)" :key="o" :label="o" :value="o" />
            </el-select>
            <el-input
              v-else
              v-model="form[k]"
              size="small"
              :placeholder="placeholder || '如 16px / 50% / auto'"
              @change="setField(k, form[k])"
            />
          </div>
        </el-collapse-item>

        <el-collapse-item title="响应式断点" name="responsive">
          <div class="wp-style-row">
            <label>断点</label>
            <el-select v-model="breakpoint" size="small" style="flex: 1" @change="syncResponsive">
              <el-option v-for="bp in BREAKPOINTS" :key="bp.key" :label="bp.label" :value="bp.key" />
            </el-select>
          </div>
          <div class="wp-style-row wp-style-row-top">
            <label>覆盖样式</label>
            <el-input
              v-model="responsiveJson"
              type="textarea"
              :rows="5"
              class="wp-mono"
              placeholder='{"fontSize":"12px","padding":"4px"}'
            />
          </div>
          <div class="wp-style-actions">
            <el-button size="small" type="primary" @click="applyResponsive">应用断点</el-button>
            <el-button size="small" @click="removeResponsive">移除断点</el-button>
          </div>
          <div v-if="responsiveKeys.length" class="wp-style-badges">
            <el-tag v-for="k in responsiveKeys" :key="k" size="small" closable @close="removeBreakpoint(k)">
              {{ k }}
            </el-tag>
          </div>
          <div class="wp-style-row wp-style-row-top">
            <label>隐藏于</label>
            <el-checkbox-group v-model="hideOn" size="small" @change="applyHideOn">
              <el-checkbox v-for="bp in BREAKPOINTS" :key="bp.key" :value="bp.key" :label="bp.key" />
            </el-checkbox-group>
          </div>
          <div class="wp-style-row">
            <label>入场动效</label>
            <el-select v-model="motion" size="small" style="flex: 1" clearable @change="applyMotion">
              <el-option label="无" value="" />
              <el-option label="淡入" value="fade-in" />
              <el-option label="上浮淡入" value="fade-up" />
              <el-option label="缩放淡入" value="zoom-in" />
            </el-select>
          </div>
          <p class="wp-style-tip">断点通过 @media 注入；xs &lt; 576，sm 576–767，md 768–991，lg 992–1199，xl ≥ 1200。</p>
        </el-collapse-item>
      </el-collapse>

      <div class="wp-style-block">
        <div class="wp-style-block-title">自定义 CSS（可选，运行态追加到节点）</div>
        <el-input
          v-model="customCss"
          type="textarea"
          :rows="5"
          class="wp-mono"
          placeholder="例如：box-shadow: 0 2px 8px rgba(0,0,0,.15);"
          @change="setCustomCss"
        />
      </div>

      <div class="wp-style-block">
        <div class="wp-style-block-title">style JSON（完整同步）</div>
        <el-input v-model="styleJson" type="textarea" :rows="5" class="wp-mono" @change="setStyleJson" />
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { useSchemaStore } from "@/store/schema";
import { commit, prettyJson } from "../util";

const props = defineProps<{ nodeId: string }>();
const schema = useSchemaStore();
const node = computed(() => schema.node(props.nodeId));

const open = ref<string[]>(["layout", "size", "typography", "responsive"]);
const breakpoint = ref("md");
const responsiveJson = ref("{}");
const hideOn = ref<string[]>([]);
const motion = ref("");

interface Section {
  key: string;
  title: string;
  fields: [string, string, string?][];
}

const SECTIONS: Section[] = [
  {
    key: "layout",
    title: "布局",
    fields: [
      ["display", "display"],
      ["position", "position"],
      ["top", "top"],
      ["right", "right"],
      ["bottom", "bottom"],
      ["left", "left"],
      ["zIndex", "z-index"],
      ["flexDirection", "flex-direction"],
      ["flexWrap", "flex-wrap"],
      ["alignItems", "align-items"],
      ["justifyContent", "justify-content"],
      ["gridTemplateColumns", "grid-template-columns"],
      ["overflow", "overflow"],
    ],
  },
  {
    key: "size",
    title: "尺寸",
    fields: [
      ["width", "宽度"],
      ["height", "高度"],
      ["minWidth", "最小宽度"],
      ["maxWidth", "最大宽度"],
      ["minHeight", "最小高度"],
      ["maxHeight", "最大高度"],
      ["boxSizing", "box-sizing"],
    ],
  },
  {
    key: "spacing",
    title: "间距",
    fields: [
      ["margin", "margin"],
      ["marginTop", "margin-top"],
      ["marginRight", "margin-right"],
      ["marginBottom", "margin-bottom"],
      ["marginLeft", "margin-left"],
      ["padding", "padding"],
      ["paddingTop", "padding-top"],
      ["paddingRight", "padding-right"],
      ["paddingBottom", "padding-bottom"],
      ["paddingLeft", "padding-left"],
      ["gap", "gap"],
    ],
  },
  {
    key: "typography",
    title: "字体",
    fields: [
      ["color", "颜色"],
      ["fontFamily", "字体"],
      ["fontSize", "字号"],
      ["fontWeight", "字重"],
      ["lineHeight", "行高"],
      ["letterSpacing", "字距"],
      ["textAlign", "对齐"],
      ["textDecoration", "装饰"],
      ["whiteSpace", "换行"],
    ],
  },
  {
    key: "background",
    title: "背景",
    fields: [
      ["backgroundColor", "背景色"],
      ["backgroundImage", "背景图"],
      ["backgroundSize", "背景尺寸"],
      ["backgroundPosition", "背景位置"],
      ["backgroundRepeat", "背景重复"],
    ],
  },
  {
    key: "border",
    title: "边框",
    fields: [
      ["border", "border"],
      ["borderWidth", "边框宽度"],
      ["borderStyle", "边框样式"],
      ["borderColor", "边框颜色"],
      ["borderRadius", "圆角"],
      ["boxShadow", "阴影"],
      ["outline", "outline"],
    ],
  },
  {
    key: "effect",
    title: "效果",
    fields: [
      ["opacity", "透明度"],
      ["transform", "transform"],
      ["transition", "transition"],
      ["animation", "animation"],
      ["cursor", "cursor"],
    ],
  },
];

const ALL_KEYS = SECTIONS.flatMap((s) => s.fields.map((x) => x[0]));

const form = reactive<Record<string, string>>({});
const customCss = ref("");
const styleJson = ref("{}");

const responsiveKeys = computed(() => Object.keys(node.value?.responsive || {}));

function alignOptions(k: string): string[] {
  if (k === "textAlign") return ["left", "center", "right", "justify"];
  if (k === "textDecoration") return ["none", "underline", "line-through", "overline"];
  return ["normal", "nowrap", "pre-wrap", "break-spaces"];
}
function layoutOptions(k: string): string[] {
  if (k === "display") return ["block", "inline", "inline-block", "flex", "inline-flex", "grid", "none"];
  if (k === "position") return ["static", "relative", "absolute", "fixed", "sticky"];
  if (k === "flexDirection") return ["row", "row-reverse", "column", "column-reverse"];
  if (k === "flexWrap") return ["nowrap", "wrap", "wrap-reverse"];
  if (k === "alignItems") return ["stretch", "flex-start", "center", "flex-end", "baseline"];
  return ["flex-start", "center", "flex-end", "space-between", "space-around", "space-evenly"];
}

function resetForm() {
  const nn = node.value;
  const s: Record<string, any> = nn?.style ?? {};
  const l: Record<string, any> | null = nn?.layout ?? null;
  for (const k of ALL_KEYS) {
    let src: any = s[k];
    if (l && (k === "width" || k === "height")) src = l[k];
    form[k] = src === undefined || src === null ? "" : String(src);
  }
  customCss.value = nn?.customCss ?? "";
  styleJson.value = prettyJson(s);
  syncResponsive();
}

function syncResponsive() {
  const style = node.value?.responsive?.[breakpoint.value] || {};
  responsiveJson.value = prettyJson(style);
}

function setField(key: string, raw: string) {
  const v = (raw ?? "").trim();
  commit(`样式 ${key}`, () => {
    const n = node.value;
    if (!n) return;
    if (n.layout && (key === "width" || key === "height")) {
      const num = parseFloat(v);
      if (isFinite(num)) n.layout[key] = Math.max(24, num);
      return;
    }
    if (v) n.style = { ...(n.style || {}), [key]: v };
    else if (n.style) {
      const next = { ...n.style };
      delete next[key];
      n.style = next;
    }
  });
  resetForm();
}

function applyResponsive() {
  try {
    const parsed = JSON.parse(responsiveJson.value.trim() || "{}");
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      ElMessage.error("断点样式必须是对象");
      return;
    }
    commit(`响应式 ${breakpoint.value}`, () => schema.setNodeResponsive(props.nodeId, breakpoint.value, parsed));
    syncResponsive();
  } catch {
    ElMessage.error("断点样式 JSON 解析失败");
  }
}

function removeResponsive() {
  commit(`移除响应式 ${breakpoint.value}`, () => schema.setNodeResponsive(props.nodeId, breakpoint.value, {}));
  syncResponsive();
}

function applyHideOn() {
  commit("响应式隐藏", () => schema.setNodeHideOn(props.nodeId, hideOn.value));
}

function syncHideOn() {
  hideOn.value = [...(node.value?.hideOn || [])];
}

function applyMotion() {
  commit("入场动效", () => schema.setNodeMotion(props.nodeId, motion.value));
}

function syncMotion() {
  motion.value = node.value?.motion || "";
}

function removeBreakpoint(bp: string) {
  commit(`移除响应式 ${bp}`, () => schema.setNodeResponsive(props.nodeId, bp, {}));
  if (bp === breakpoint.value) syncResponsive();
}

function setCustomCss() {
  commit("自定义 CSS", () => {
    const n = node.value;
    if (!n) return;
    const v = customCss.value.trim();
    if (v) n.customCss = v;
    else delete n.customCss;
  });
}

function setStyleJson() {
  try {
    const parsed = JSON.parse(styleJson.value.trim() || "{}");
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      ElMessage.error("style JSON 必须是对象");
      resetForm();
      return;
    }
    commit("样式 JSON", () => {
      const n = node.value;
      if (!n) return;
      n.style = { ...parsed };
    });
    resetForm();
  } catch {
    ElMessage.error("style JSON 解析失败");
    resetForm();
  }
}

const BREAKPOINTS = [
  { key: "xs", label: "xs（<576）" },
  { key: "sm", label: "sm（576–767）" },
  { key: "md", label: "md（768–991）" },
  { key: "lg", label: "lg（992–1199）" },
  { key: "xl", label: "xl（≥1200）" },
];

watch(() => props.nodeId, resetForm, { immediate: true });
watch(() => node.value?.style, resetForm, { deep: true });
watch(() => node.value?.layout, resetForm, { deep: true });
watch(() => node.value?.responsive, syncResponsive, { deep: true });
watch(() => node.value?.hideOn, syncHideOn, { deep: true, immediate: true });
watch(() => node.value?.motion, syncMotion, { immediate: true });
watch(breakpoint, syncResponsive);
</script>

<style scoped>
.wp-style {
  font-size: 13px;
  padding: 4px 2px;
}
.wp-style-collapse :deep(.el-collapse-item__header) {
  font-size: 13px;
}
.wp-style-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.wp-style-row-top {
  align-items: flex-start;
}
.wp-style-row label {
  width: 116px;
  flex: none;
  color: var(--el-text-color-regular);
  font-size: 12px;
}
.wp-style-row :deep(.el-input),
.wp-style-row :deep(.el-select) {
  flex: 1;
}
.wp-style-actions {
  display: flex;
  gap: 6px;
  margin-bottom: 6px;
}
.wp-style-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.wp-style-tip {
  color: var(--el-text-color-secondary);
  font-size: 11px;
  line-height: 1.5;
  margin: 8px 0 0;
}
.wp-style-block {
  margin-top: 12px;
}
.wp-style-block-title {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 6px;
}
.wp-mono :deep(textarea) {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 12px;
}
</style>
