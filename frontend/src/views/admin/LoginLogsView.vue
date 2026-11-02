<template>
  <div class="wp-admin-page">
    <div class="wp-page-header">
      <div class="wp-page-title-block">
        <h2>登录日志</h2>
        <p class="wp-page-desc">记录登录成功、失败、IP 和 User-Agent。</p>
      </div>
      <el-button @click="load">刷新</el-button>
    </div>

    <el-card>
      <div class="wp-filter-bar">
        <el-input v-model="username" placeholder="用户名" clearable style="width: 180px" @keyup.enter="reload" @clear="reload" />
        <el-select v-model="success" clearable placeholder="全部结果" style="width: 130px" @change="reload">
          <el-option label="成功" value="1" />
          <el-option label="失败" value="0" />
        </el-select>
        <el-button @click="reload">查询</el-button>
      </div>

      <el-table :data="logs" v-loading="loading" border stripe>
        <el-table-column label="时间" width="180">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="username" label="用户名" width="150" />
        <el-table-column label="结果" width="90">
          <template #default="{ row }">
            <el-tag :type="row.success ? 'success' : 'danger'" size="small">{{ row.success ? "成功" : "失败" }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="reason" label="原因" min-width="180">
          <template #default="{ row }">{{ row.reason || "—" }}</template>
        </el-table-column>
        <el-table-column prop="ip" label="IP" width="150">
          <template #default="{ row }">{{ row.ip || "—" }}</template>
        </el-table-column>
        <el-table-column prop="user_agent" label="User-Agent" min-width="260" show-overflow-tooltip />
        <template #empty><el-empty description="暂无登录记录" :image-size="60" /></template>
      </el-table>

      <div class="wp-pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="size"
          :page-sizes="[20, 50, 100]"
          :total="total"
          layout="total, sizes, prev, pager, next"
          @current-change="load"
          @size-change="reload"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { api } from "@/api";
import { formatTime } from "@/utils";

const loading = ref(false);
const logs = ref<any[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);
const username = ref("");
const success = ref("");

async function load() {
  loading.value = true;
  try {
    const qs = new URLSearchParams({ page: String(page.value), size: String(size.value) });
    if (username.value.trim()) qs.set("username", username.value.trim());
    if (success.value) qs.set("success", success.value);
    const data = await api.get<any>(`/auth/login-logs/?${qs.toString()}`);
    logs.value = data?.results || [];
    total.value = Number(data?.count) || 0;
  } catch (error: any) {
    ElMessage.error(error?.message || "加载登录日志失败");
  } finally {
    loading.value = false;
  }
}

function reload() {
  page.value = 1;
  load();
}

onMounted(load);
</script>
