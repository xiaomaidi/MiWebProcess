<template>
  <div class="wp-admin-page" v-loading="loadingApp">
    <div class="wp-page-header" v-if="app">
      <div class="wp-page-title-block">
        <h2>
          {{ app.name }}
          <el-tag :type="appStatusType(app.status)" size="small">{{ appStatusText(app.status) }}</el-tag>
          <el-tag type="info" size="small" effect="plain">{{ app.code }}</el-tag>
        </h2>
        <p class="wp-page-desc">{{ app.description || "暂无描述" }}</p>
      </div>
      <div class="wp-page-actions">
        <el-button type="primary" plain @click="aiSiteOpen = true">✨ AI 建站</el-button>
        <el-button @click="router.push(`/admin/agent?app_id=${appId}`)">高级 Agent</el-button>
        <el-button type="primary" @click="openAppPublish">发布应用</el-button>
        <el-dropdown @command="onAppMore">
          <el-button>更多 <el-icon><ArrowDown /></el-icon></el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="ops">扩展能力</el-dropdown-item>
              <el-dropdown-item command="settings">应用设置</el-dropdown-item>
              <el-dropdown-item command="auth">认证设置</el-dropdown-item>
              <el-dropdown-item command="tokens">设计 Token</el-dropdown-item>
              <el-dropdown-item command="workflow">工作流设计</el-dropdown-item>
              <el-dropdown-item divided command="edit">编辑应用</el-dropdown-item>
              <el-dropdown-item command="export">导出模板</el-dropdown-item>
              <el-dropdown-item command="clone">克隆应用</el-dropdown-item>
              <el-dropdown-item divided command="archive">归档应用</el-dropdown-item>
              <el-dropdown-item command="delete">删除应用</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>

    <div v-if="app" class="app-detail-stats">
      <button class="app-detail-stat" @click="tab = 'pages'; onTabChange('pages')">
        <span>页面</span><strong>{{ pages.length }}</strong><small>已搭建页面</small>
      </button>
      <button class="app-detail-stat" @click="tab = 'models'; onTabChange('models')">
        <span>数据模型</span><strong>{{ models.length }}</strong><small>业务数据结构</small>
      </button>
      <button class="app-detail-stat" @click="tab = 'releases'; onTabChange('releases')">
        <span>发布记录</span><strong>{{ releases.length }}</strong><small>版本与灰度</small>
      </button>
      <div class="app-detail-stat is-static">
        <span>应用状态</span>
        <strong class="is-status"><el-tag :type="appStatusType(app.status)" size="small">{{ appStatusText(app.status) }}</el-tag></strong>
        <small>{{ app.code }}</small>
      </div>
    </div>

    <el-card v-if="app">
      <el-tabs v-model="tab" @tab-change="onTabChange">
        <!-- ================= 页面 ================= -->
        <el-tab-pane label="页面" name="pages">
          <div class="wp-tab-toolbar">
            <el-button type="primary" size="small" @click="openPageCreate">新建页面</el-button>
            <el-button size="small" @click="loadPages">刷新</el-button>
          </div>
          <el-table :data="pages" v-loading="loadingPages" border stripe>
            <el-table-column prop="name" label="名称" min-width="140" />
            <el-table-column prop="path" label="路径" min-width="120" />
            <el-table-column label="类型" width="90">
              <template #default="{ row }">
                <el-tag size="small" effect="plain">{{ row.type }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag :type="pageStatusType(row.status)" size="small">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="version" label="版本" width="70" />
            <el-table-column label="更新时间" width="160">
              <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="330" fixed="right">
              <template #default="{ row }">
                <el-button size="small" @click="router.push(`/design/${appId}/${row.id}`)">设计</el-button>
                <el-button size="small" @click="router.push(`/preview/${appId}/${row.id}`)">预览</el-button>
                <el-button size="small" @click="openRuntime(row)">线上</el-button>
                <el-button size="small" type="primary" @click="openPagePublish(row)">发布</el-button>
                <el-button size="small" @click="openPageVersions(row)">版本</el-button>
              </template>
            </el-table-column>
            <template #empty><el-empty description="暂无页面" :image-size="60" /></template>
          </el-table>
        </el-tab-pane>

        <!-- ================= 数据源 ================= -->
        <el-tab-pane label="数据源" name="datasources">
          <div class="wp-tab-toolbar">
            <el-button type="primary" size="small" @click="openDsCreate">新建数据源</el-button>
            <el-button size="small" @click="loadDss">刷新</el-button>
          </div>
          <el-table :data="dss" v-loading="loadingDss" border stripe>
            <el-table-column prop="name" label="名称" min-width="140" />
            <el-table-column prop="type" label="类型" width="90" />
            <el-table-column label="测试结果" width="100">
              <template #default="{ row }">
                <el-tag :type="dsStatusType(row.test_status)" size="small">{{ dsStatusText(row.test_status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="最近测试" width="160">
              <template #default="{ row }">{{ row.last_test_at ? formatTime(row.last_test_at) : "—" }}</template>
            </el-table-column>
            <el-table-column label="操作" width="200" fixed="right">
              <template #default="{ row }">
                <el-button size="small" @click="testDs(row)">测试</el-button>
                <el-button size="small" @click="openDsEdit(row)">编辑</el-button>
                <el-button size="small" type="danger" plain @click="deleteDs(row)">删除</el-button>
              </template>
            </el-table-column>
            <template #empty><el-empty description="暂无数据源" :image-size="60" /></template>
          </el-table>
        </el-tab-pane>

        <!-- ================= 数据模型 ================= -->
        <el-tab-pane label="数据模型" name="models">
          <div class="wp-tab-toolbar">
            <el-button type="primary" size="small" @click="openModelCreate">新建模型</el-button>
            <el-button size="small" type="primary" plain @click="aiModelOpen = true">✨ AI 建模</el-button>
            <el-button size="small" @click="generatorOpen = true">生成主子表</el-button>
            <el-button size="small" @click="loadModels">刷新</el-button>
          </div>
          <el-table :data="models" v-loading="loadingModels" border stripe>
            <el-table-column prop="name" label="名称" min-width="140" />
            <el-table-column label="公开读取" width="90">
              <template #default="{ row }">
                <el-tag :type="row.is_public ? 'success' : 'info'" size="small">{{ row.is_public ? "公开" : "私有" }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="字段数" width="90">
              <template #default="{ row }">{{ (row.fields || []).length }}</template>
            </el-table-column>
            <el-table-column label="更新时间" width="170">
              <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="410" fixed="right">
              <template #default="{ row }">
                <el-button size="small" @click="openModelDetail(row)">查看</el-button>
                <el-button size="small" type="primary" plain @click="router.push(`/admin/models/${row.id}`)">数据管理</el-button>
                <el-button size="small" @click="router.push(`/admin/models/${row.id}/report`)">报表</el-button>
                <el-button size="small" @click="openModelEdit(row)">编辑</el-button>
                <el-button size="small" type="danger" plain @click="deleteModel(row)">删除</el-button>
              </template>
            </el-table-column>
            <template #empty><el-empty description="暂无数据模型" :image-size="60" /></template>
          </el-table>
        </el-tab-pane>

        <!-- ================= 成员 ================= -->
        <el-tab-pane label="成员" name="members">
          <div class="wp-tab-toolbar">
            <el-button type="primary" size="small" @click="openMemberCreate">添加成员</el-button>
            <el-button size="small" @click="loadMembers">刷新</el-button>
          </div>
          <el-table :data="members" v-loading="loadingMembers" border stripe>
            <el-table-column prop="username" label="用户名" min-width="140" />
            <el-table-column label="角色" width="120">
              <template #default="{ row }">
                <el-tag size="small" :type="row.role === 'owner' ? 'danger' : row.role === 'editor' ? 'primary' : 'info'">
                  {{ roleText(row.role) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="180" fixed="right">
              <template #default="{ row }">
                <el-button size="small" @click="changeRole(row)">改角色</el-button>
                <el-button size="small" type="danger" plain @click="removeMember(row)">移除</el-button>
              </template>
            </el-table-column>
            <template #empty><el-empty description="暂无成员" :image-size="60" /></template>
          </el-table>
        </el-tab-pane>

        <!-- ================= 发布记录 ================= -->
        <el-tab-pane label="发布记录" name="releases">
          <div class="wp-tab-toolbar">
            <el-button type="primary" size="small" @click="openAppPublish">发布应用</el-button>
            <el-button size="small" @click="loadReleases">刷新</el-button>
          </div>
          <el-table :data="releases" v-loading="loadingReleases" border stripe>
            <el-table-column prop="version" label="版本" width="80" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="releaseStatusType(row.status)" size="small">{{ releaseStatusText(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="灰度比例" width="90">
              <template #default="{ row }">{{ row.traffic_ratio }}%</template>
            </el-table-column>
            <el-table-column prop="changelog" label="变更说明" min-width="200" show-overflow-tooltip />
            <el-table-column label="发布时间" width="160">
              <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="180" fixed="right">
              <template #default="{ row }">
                <el-button size="small" @click="openTraffic(row)">灰度</el-button>
                <el-button size="small" @click="rollbackRelease(row)">回滚</el-button>
              </template>
            </el-table-column>
            <template #empty><el-empty description="暂无发布记录" :image-size="60" /></template>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- ============ 对话框 ============ -->
    <el-dialog v-model="dlg.app" title="编辑应用" width="480px">
      <el-form :model="appForm" label-width="80px">
        <el-form-item label="名称"><el-input v-model="appForm.name" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="appForm.description" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg.app = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveApp">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="dlg.appPublish" title="发布应用" width="480px">
      <el-form label-width="80px">
        <el-form-item label="变更说明">
          <el-input v-model="appPublishChangelog" type="textarea" :rows="3" placeholder="本次发布说明（可选）" />
        </el-form-item>
      </el-form>
      <p class="wp-dialog-hint">发布将逐页校验并创建快照，未发布的页面会随本次发布补建。</p>
      <template #footer>
        <el-button @click="dlg.appPublish = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="publishApp">确认发布</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="dlg.page" title="新建页面" width="480px">
      <el-form :model="pageForm" label-width="80px">
        <el-form-item label="名称"><el-input v-model="pageForm.name" placeholder="如：首页" /></el-form-item>
        <el-form-item label="路径">
          <el-input v-model="pageForm.path" placeholder="单段 slug，如 home" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="pageForm.type" style="width: 100%">
            <el-option label="页面 page" value="page" />
            <el-option label="布局 layout" value="layout" />
            <el-option label="弹窗 popup" value="popup" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg.page = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="createPage">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="dlg.pagePublish" title="发布页面" width="480px">
      <el-form label-width="80px">
        <el-form-item label="变更说明">
          <el-input v-model="pagePublishChangelog" type="textarea" :rows="3" placeholder="本次发布说明（可选）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg.pagePublish = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="publishPage">确认发布</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="dlg.pageVersions" title="页面版本" width="620px">
      <el-table :data="pageVersions" v-loading="loadingPageVersions" size="small" border>
        <el-table-column prop="version" label="版本" width="80" />
        <el-table-column label="发布人" width="120">
          <template #default="{ row }">{{ row.publisher || row.publisher_id }}</template>
        </el-table-column>
        <el-table-column label="发布时间" width="160">
          <template #default="{ row }">{{ formatTime(row.published_at) }}</template>
        </el-table-column>
        <el-table-column prop="changelog" label="变更说明" min-width="140" show-overflow-tooltip />
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button size="small" @click="rollbackPageVersion(row)">回滚至此</el-button>
          </template>
        </el-table-column>
        <template #empty><el-empty description="暂无版本" :image-size="40" /></template>
      </el-table>
      <template #footer>
        <el-button @click="dlg.pageVersions = false">关闭</el-button>
      </template>
    </el-dialog>

    <DatasourceDialog
      v-model="dlg.ds"
      :app-id="appId"
      :editing="editingDs"
      @saved="loadDss"
    />

    <AiSiteDialog v-model="aiSiteOpen" :app-id="appId" @created="loadPages" />
    <AiModelDialog v-model="aiModelOpen" :app-id="appId" @generated="onAiModelGenerated" />
    <MasterDetailGenerator
      v-model="generatorOpen"
      :app-id="appId"
      :models="models"
      @generated="onMasterDetailGenerated"
    />

    <el-dialog v-model="dlg.model" :title="modelEditingId === null ? '新建数据模型' : '编辑数据模型'" width="960px">
      <el-form :model="modelForm" label-width="80px">
        <el-form-item label="名称"><el-input v-model="modelForm.name" :disabled="modelEditingId !== null" /></el-form-item>
        <el-form-item label="公开读取">
          <el-switch v-model="modelForm.isPublic" />
          <span class="wp-hint" style="margin-left: 8px">开启后运行时可匿名读取（内容门户）</span>
        </el-form-item>
        <el-form-item label="数据范围">
          <el-select v-model="modelForm.dataScope" style="width: 100%">
            <el-option label="全部数据" value="all" />
            <el-option label="仅本人数据（按归属字段）" value="owner" />
          </el-select>
        </el-form-item>
        <el-form-item label="审批流程">
          <el-select v-model="modelForm.workflowDefinitionId" clearable filterable placeholder="不绑定" style="width: 100%">
            <el-option v-for="w in workflows" :key="w.id" :label="`${w.name}（${w.status}）`" :value="w.id" />
          </el-select>
          <span class="wp-hint" style="margin-left: 8px">绑定后通用记录详情页会自动显示审批面板</span>
        </el-form-item>
        <el-form-item v-if="modelForm.dataScope === 'owner'" label="行级归属字段">
          <el-select v-model="modelForm.rowOwnerField" clearable filterable allow-create placeholder="选择归属字段" style="width: 100%">
            <el-option v-for="f in modelFieldsDraft" :key="f.name" :label="`${f.label || f.name} (${f.name})`" :value="f.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="操作权限">
          <div style="width: 100%">
            <el-button size="small" type="primary" plain style="margin-bottom: 6px" @click="suggestPermissions">
              ✨ AI 权限建议
            </el-button>
            <el-table :data="actionRoleRows" size="small" border style="width: 100%">
            <el-table-column prop="label" label="操作" width="90" />
            <el-table-column label="允许角色（留空=全部）">
              <template #default="{ row }">
                <el-select v-model="modelForm.actionRoles[row.key]" multiple collapse-tags size="small" placeholder="全部">
                  <el-option label="查看者" value="viewer" />
                  <el-option label="编辑者" value="editor" />
                  <el-option label="所有者" value="owner" />
                </el-select>
              </template>
            </el-table-column>
            </el-table>
          </div>
        </el-form-item>
        <el-form-item label="字段">
          <div class="wp-field-builder">
            <el-table :data="modelFieldsDraft" size="small" border>
              <el-table-column label="字段名" width="130">
                <template #default="{ row }"><el-input v-model="row.name" size="small" placeholder="title" /></template>
              </el-table-column>
              <el-table-column label="显示名" width="130">
                <template #default="{ row }"><el-input v-model="row.label" size="small" placeholder="标题" /></template>
              </el-table-column>
              <el-table-column label="类型" width="110">
                <template #default="{ row }">
                  <el-select v-model="row.type" size="small" style="width: 100%">
                    <el-option label="文本" value="string" />
                    <el-option label="数字" value="number" />
                    <el-option label="布尔" value="boolean" />
                    <el-option label="日期" value="date" />
                    <el-option label="JSON" value="json" />
                    <el-option label="引用" value="reference" />
                  </el-select>
                </template>
              </el-table-column>
              <el-table-column label="控件" width="104">
                <template #default="{ row }">
                  <el-select v-model="row.ui" size="small" clearable placeholder="自动">
                    <el-option label="文本框" value="text" />
                    <el-option label="多行" value="textarea" />
                    <el-option label="富文本" value="richtext" />
                  </el-select>
                </template>
              </el-table-column>
              <el-table-column label="关联模型" width="150">
                <template #default="{ row }">
                  <el-select v-if="row.type === 'reference'" v-model="row.ref_model" size="small" filterable placeholder="选择模型">
                    <el-option v-for="m in models" :key="m.id" :label="m.name" :value="m.name" />
                  </el-select>
                  <span v-else class="wp-muted-cell">—</span>
                </template>
              </el-table-column>
              <el-table-column label="必填" width="64">
                <template #default="{ row }"><el-switch v-model="row.required" size="small" /></template>
              </el-table-column>
              <el-table-column label="可读角色" width="150">
                <template #default="{ row }">
                  <el-select v-model="row.read_roles" multiple collapse-tags size="small" placeholder="全部">
                    <el-option label="查看者" value="viewer" />
                    <el-option label="编辑者" value="editor" />
                    <el-option label="所有者" value="owner" />
                  </el-select>
                </template>
              </el-table-column>
              <el-table-column label="可写角色" width="150">
                <template #default="{ row }">
                  <el-select v-model="row.write_roles" multiple collapse-tags size="small" placeholder="全部">
                    <el-option label="查看者" value="viewer" />
                    <el-option label="编辑者" value="editor" />
                    <el-option label="所有者" value="owner" />
                  </el-select>
                </template>
              </el-table-column>
              <el-table-column label="脱敏角色" width="140">
                <template #default="{ row }">
                  <el-select v-model="row.mask_roles" multiple collapse-tags size="small" placeholder="不脱敏">
                    <el-option label="查看者" value="viewer" />
                    <el-option label="编辑者" value="editor" />
                    <el-option label="所有者" value="owner" />
                  </el-select>
                </template>
              </el-table-column>
              <el-table-column width="48" align="center">
                <template #default="{ $index }">
                  <el-button size="small" text type="danger" @click="modelFieldsDraft.splice($index, 1)">×</el-button>
                </template>
              </el-table-column>
            </el-table>
            <el-button size="small" style="margin-top: 6px" @click="addModelField">+ 添加字段</el-button>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg.model = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveModel">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="dlg.modelDetail" title="模型字段" width="560px">
      <el-table :data="modelDetailFields" size="small" border>
        <el-table-column prop="name" label="字段" min-width="120" />
        <el-table-column prop="type" label="类型" width="100" />
        <el-table-column label="必填" width="70">
          <template #default="{ row }">{{ row.required ? "是" : "否" }}</template>
        </el-table-column>
        <el-table-column label="默认值" width="100">
          <template #default="{ row }">{{ row.default === undefined ? "—" : JSON.stringify(row.default) }}</template>
        </el-table-column>
        <el-table-column prop="description" label="说明" min-width="120" />
      </el-table>
      <template #footer>
        <el-button @click="dlg.modelDetail = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="dlg.member" title="添加成员" width="480px">
      <el-form :model="memberForm" label-width="80px">
        <el-form-item label="用户 ID">
          <el-input-number v-model="memberForm.user_id" :min="1" controls-position="right" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="memberForm.role" style="width: 100%">
            <el-option label="owner" value="owner" />
            <el-option label="editor" value="editor" />
            <el-option label="viewer" value="viewer" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg.member = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="createMember">添加</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="dlg.role" title="修改角色" width="420px">
      <el-form label-width="80px">
        <el-form-item label="角色">
          <el-select v-model="roleTarget.role" style="width: 100%">
            <el-option label="owner" value="owner" />
            <el-option label="editor" value="editor" />
            <el-option label="viewer" value="viewer" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg.role = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveRole">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="dlg.traffic" title="灰度比例" width="420px">
      <el-form label-width="80px">
        <el-form-item label="比例 %">
          <el-input-number v-model="trafficTarget.ratio" :min="0" :max="100" controls-position="right" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg.traffic = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveTraffic">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { ArrowDown } from "@element-plus/icons-vue";
import { api } from "@/api";
import MasterDetailGenerator from "./MasterDetailGenerator.vue";
import DatasourceDialog from "@/designer/components/DatasourceDialog.vue";
import AiSiteDialog from "./AiSiteDialog.vue";
import AiModelDialog from "./AiModelDialog.vue";
import { formatTime } from "@/utils";
import type {
  AppInfo,
  AppMember,
  DataModelInfo,
  DataSourceDef,
  PageInfo,
  PageVersionInfo,
  Paged,
  ReleaseInfo,
} from "@/types";

const route = useRoute();
const router = useRouter();

const appId = computed(() => Number(route.params.appId));
const app = ref<AppInfo | null>(null);
const tab = ref("pages");

const loadingApp = ref(false);
const loadingPages = ref(false);
const loadingDss = ref(false);
const loadingModels = ref(false);
const loadingMembers = ref(false);
const loadingReleases = ref(false);
const loadingPageVersions = ref(false);
const saving = ref(false);

const pages = ref<PageInfo[]>([]);
type DsRow = DataSourceDef & { test_status?: string; last_test_at?: string };
const dss = ref<DsRow[]>([]);
const models = ref<DataModelInfo[]>([]);
const members = ref<AppMember[]>([]);
const releases = ref<ReleaseInfo[]>([]);
const pageVersions = ref<PageVersionInfo[]>([]);

const dlg = reactive({
  app: false,
  appPublish: false,
  page: false,
  pagePublish: false,
  pageVersions: false,
  ds: false,
  model: false,
  modelDetail: false,
  member: false,
  role: false,
  traffic: false,
});

const appForm = reactive({ name: "", description: "" });
const appPublishChangelog = ref("");
const pageForm = reactive({ name: "", path: "", type: "page" as PageInfo["type"] });
const pagePublishChangelog = ref("");
let pagePublishTarget: PageInfo | null = null;
let pageVersionsTarget: PageInfo | null = null;
const editingDs = ref<DataSourceDef | null>(null);
const generatorOpen = ref(false);
const aiSiteOpen = ref(false);
const aiModelOpen = ref(false);
const modelForm = reactive({
  name: "",
  isPublic: false,
  rowOwnerField: "",
  dataScope: "all",
  actionRoles: {} as Record<string, string[]>,
  workflowDefinitionId: null as number | null,
});
const workflows = ref<{ id: number; name: string; status: string }[]>([]);
function normalizeActionRoles(raw: Record<string, any> = {}): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const row of actionRoleRows) out[row.key] = Array.isArray(raw[row.key]) ? [...raw[row.key]] : [];
  return out;
}

const actionRoleRows = [
  { key: "view", label: "查看" },
  { key: "create", label: "新增" },
  { key: "update", label: "编辑" },
  { key: "delete", label: "删除" },
  { key: "export", label: "导出" },
];
const modelFieldsDraft = ref<any[]>([]);

function addModelField() {
  modelFieldsDraft.value.push({ name: "", label: "", type: "string", required: false, read_roles: [], write_roles: [], mask_roles: [] });
}
let modelEditingId: number | null = null;
const modelDetailFields = ref<{ name: string; type: string; required?: boolean; default?: any; description?: string }[]>([]);
const memberForm = reactive({ user_id: 1, role: "editor" as AppMember["role"] });
const roleTarget = reactive<{ user_id: number; role: AppMember["role"] }>({ user_id: 0, role: "viewer" });
const trafficTarget = reactive<{ id: number; ratio: number }>({ id: 0, ratio: 100 });

// ============ 通用工具 ============
function asList<T>(data: unknown): T[] {
  if (Array.isArray(data)) return data as T[];
  const p = data as Paged<T> | null;
  if (p && Array.isArray(p.results)) return p.results;
  return [];
}

function appStatusText(status: string) {
  const map: Record<string, string> = { draft: "草稿", published: "已发布", archived: "已归档" };
  return map[status] || status;
}
function appStatusType(status: string): "warning" | "success" | "info" {
  const map: Record<string, "warning" | "success" | "info"> = { draft: "warning", published: "success", archived: "info" };
  return map[status] || "info";
}
function pageStatusType(status: string): "warning" | "success" | "info" {
  const map: Record<string, "warning" | "success" | "info"> = { draft: "warning", published: "success", archived: "info" };
  return map[status] || "info";
}
function dsStatusType(status?: string): "success" | "danger" | "info" {
  const map: Record<string, "success" | "danger" | "info"> = { ok: "success", fail: "danger", unknown: "info" };
  return (status && map[status]) || "info";
}
function dsStatusText(status?: string) {
  const map: Record<string, string> = { ok: "通过", fail: "失败", unknown: "未测试" };
  return map[status || ""] || status || "未测试";
}
function releaseStatusType(status: string): "success" | "warning" | "info" | "danger" {
  const map: Record<string, "success" | "warning" | "info" | "danger"> = {
    pending: "info",
    releasing: "warning",
    active: "success",
    rollback: "warning",
    failed: "danger",
  };
  return map[status] || "info";
}
function releaseStatusText(status: string) {
  const map: Record<string, string> = {
    pending: "待发布",
    releasing: "发布中",
    active: "生效",
    rollback: "已回滚",
    failed: "失败",
  };
  return map[status] || status;
}
function roleText(role: string) {
  const map: Record<string, string> = { owner: "所有者", editor: "编辑者", viewer: "只读" };
  return map[role] || role;
}

// ============ 应用 ============
async function loadApp() {
  loadingApp.value = true;
  try {
    app.value = await api.get<AppInfo>(`/apps/${appId.value}/`);
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "加载应用失败");
  } finally {
    loadingApp.value = false;
  }
}

function openAppEdit() {
  if (!app.value) return;
  appForm.name = app.value.name;
  appForm.description = app.value.description || "";
  dlg.app = true;
}

async function saveApp() {
  if (!app.value) return;
  saving.value = true;
  try {
    await api.put(`/apps/${app.value.id}/`, {
      name: appForm.name,
      description: appForm.description || null,
    });
    ElMessage.success("已保存");
    dlg.app = false;
    loadApp();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "保存失败");
  } finally {
    saving.value = false;
  }
}

function openAppPublish() {
  appPublishChangelog.value = "";
  dlg.appPublish = true;
}

async function publishApp() {
  if (!app.value) return;
  saving.value = true;
  try {
    await api.post(`/apps/${app.value.id}/releases/`, {
      changelog: appPublishChangelog.value || undefined,
    });
    ElMessage.success("发布成功");
    dlg.appPublish = false;
    loadApp();
    loadReleases();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "发布失败");
  } finally {
    saving.value = false;
  }
}

async function deleteApp() {
  if (!app.value) return;
  const current = app.value;
  try {
    await ElMessageBox.prompt(
      `此操作会永久删除应用「${current.name}」及其页面、模型、数据和发布记录，且不可恢复。\n请输入应用编码 ${current.code} 确认：`,
      "删除应用",
      {
        type: "error",
        confirmButtonText: "永久删除",
        cancelButtonText: "取消",
        inputPlaceholder: current.code,
        inputValidator: (value: string) =>
          value === current.code || "应用编码不匹配，未执行删除",
      }
    );
  } catch {
    return;
  }
  try {
    await api.del(`/apps/${current.id}/`);
    ElMessage.success("应用已删除");
    await router.push("/admin/apps");
  } catch (error: any) {
    ElMessage.error(error?.detail || error?.message || "删除失败");
  }
}

async function exportTemplate() {
  if (!app.value) return;
  try {
    const data = await api.get<any>(`/templates/export/${appId.value}/`);
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${app.value.code}.template.json`;
    link.click();
    URL.revokeObjectURL(url);
    ElMessage.success("模板 JSON 已导出");
  } catch (error: any) {
    ElMessage.error(error?.message || "导出失败");
  }
}

async function cloneApp() {
  if (!app.value) return;
  let name = "";
  try {
    const result = await ElMessageBox.prompt("新应用名称", "克隆应用", {
      inputValue: `${app.value.name} 副本`,
      confirmButtonText: "创建",
      cancelButtonText: "取消",
    });
    name = String(result.value || "").trim();
  } catch {
    return;
  }
  if (!name) return;
  try {
    const result = await api.post<any>("/templates/clone/", {
      source_app_id: appId.value,
      name,
      code: `copy-${Date.now().toString(36)}`,
    });
    ElMessage.success("应用已克隆（页面、模型、示例数据和流程）");
    router.push(`/admin/apps/${result.app.id}`);
  } catch (error: any) {
    ElMessage.error(error?.message || "克隆失败");
  }
}

async function archiveApp() {  if (!app.value || app.value.status === "archived") return;
  try {
    await ElMessageBox.confirm(`确定归档应用「${app.value.name}」吗？`, "提示", { type: "warning" });
  } catch {
    return;
  }
  try {
    await api.post(`/apps/${app.value.id}/archive/`);
    ElMessage.success("已归档");
    router.push("/admin/apps");
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "归档失败");
  }
}

// ============ 页面 ============
async function loadPages() {
  loadingPages.value = true;
  try {
    const data = await api.get<unknown>(`/apps/${appId.value}/pages/?page=1&size=100`);
    pages.value = asList<PageInfo>(data);
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "加载页面失败");
  } finally {
    loadingPages.value = false;
  }
}

function openPageCreate() {
  pageForm.name = "";
  pageForm.path = "";
  pageForm.type = "page";
  dlg.page = true;
}

async function createPage() {
  saving.value = true;
  try {
    await api.post(`/apps/${appId.value}/pages/`, {
      name: pageForm.name,
      path: pageForm.path,
      type: pageForm.type,
    });
    ElMessage.success("页面已创建");
    dlg.page = false;
    loadPages();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "创建失败");
  } finally {
    saving.value = false;
  }
}

function openRuntime(row: PageInfo) {
  if (!app.value) return;
  window.open(`/run/${app.value.code}/${row.path}`, "_blank");
}

function openPagePublish(row: PageInfo) {
  pagePublishTarget = row;
  pagePublishChangelog.value = "";
  dlg.pagePublish = true;
}

async function publishPage() {
  if (!pagePublishTarget) return;
  saving.value = true;
  try {
    await api.post(`/pages/${pagePublishTarget.id}/publish/`, {
      changelog: pagePublishChangelog.value || undefined,
    });
    ElMessage.success("页面已发布");
    dlg.pagePublish = false;
    loadPages();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "发布失败");
  } finally {
    saving.value = false;
  }
}

async function openPageVersions(row: PageInfo) {
  pageVersionsTarget = row;
  dlg.pageVersions = true;
  loadingPageVersions.value = true;
  pageVersions.value = [];
  try {
    const data = await api.get<unknown>(`/pages/${row.id}/versions/?page=1&size=50`);
    pageVersions.value = asList<PageVersionInfo>(data);
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "加载版本失败");
  } finally {
    loadingPageVersions.value = false;
  }
}

async function rollbackPageVersion(row: PageVersionInfo) {
  if (!pageVersionsTarget) return;
  try {
    await ElMessageBox.confirm(`将版本 ${row.version} 载入草稿？`, "提示", { type: "warning" });
  } catch {
    return;
  }
  try {
    await api.post(`/pages/${pageVersionsTarget.id}/versions/${row.version}/rollback/`, {});
    ElMessage.success("已回滚");
    dlg.pageVersions = false;
    loadPages();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "回滚失败");
  }
}

// ============ 数据源 ============
async function loadDss() {
  loadingDss.value = true;
  try {
    const data = await api.get<unknown>(`/apps/${appId.value}/datasources/`);
    dss.value = asList<DataSourceDef & { test_status?: string; last_test_at?: string }>(data);
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "加载数据源失败");
  } finally {
    loadingDss.value = false;
  }
}

function openDsCreate() {
  editingDs.value = null;
  dlg.ds = true;
}

function openDsEdit(row: DataSourceDef) {
  editingDs.value = row;
  dlg.ds = true;
}

async function testDs(row: DataSourceDef) {
  const method = String((row.config as any)?.method || "GET").toUpperCase();
  const isRest = String(row.type).toLowerCase() === "rest";
  if (isRest && method !== "GET") {
    try {
      await ElMessageBox.confirm(
        `将按 ${method} 实际请求第三方，可能产生业务数据，确认继续？`,
        "测试 REST 数据源",
        { type: "warning" }
      );
    } catch {
      return;
    }
  }
  saving.value = true;
  try {
    if (isRest) {
      const res = await api.post<{ data: unknown; from_cache: boolean }>(
        `/datasources/${row.id}/query/`,
        { params: {} },
        { silent: true }
      );
      const size = Array.isArray(res.data) ? res.data.length : res.data && typeof res.data === "object" ? 1 : 0;
      ElMessage.success(`请求成功${size ? `，返回 ${size} 条` : ""}${res.from_cache ? "（缓存）" : ""}`);
      loadDss();
      return;
    }
    const res = await api.post<{ ok: boolean; message?: string; latency_ms?: number }>(
      `/datasources/${row.id}/test/`,
      {}
    );
    if (res.ok) {
      ElMessage.success(`连接成功${res.latency_ms != null ? `（${res.latency_ms}ms）` : ""}${res.message ? `：${res.message}` : ""}`);
    } else {
      ElMessage.error(res.message || "连接失败");
    }
    loadDss();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "测试失败");
  } finally {
    saving.value = false;
  }
}

async function deleteDs(row: DataSourceDef) {
  try {
    await ElMessageBox.confirm(`确定删除数据源「${row.name}」吗？`, "提示", { type: "warning" });
  } catch {
    return;
  }
  try {
    await api.del(`/datasources/${row.id}/`);
    ElMessage.success("已删除");
    loadDss();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "删除失败");
  }
}

// ============ 数据模型 ============
async function loadModels() {
  loadingModels.value = true;
  try {
    const data = await api.get<unknown>(`/apps/${appId.value}/models/`);
    models.value = asList<DataModelInfo & { updated_at?: string }>(data);
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "加载数据模型失败");
  } finally {
    loadingModels.value = false;
  }
}

async function loadWorkflows() {
  try {
    const data = await api.get<any>(`/workflows/definitions/?app_id=${appId.value}`);
    workflows.value = asList<{ id: number; name: string; status: string }>(data);
  } catch {
    workflows.value = [];
  }
}

function openModelCreate() {
  modelEditingId = null;
  modelForm.name = "";
  modelForm.isPublic = false;
  modelForm.rowOwnerField = "";
  modelForm.workflowDefinitionId = null;
  modelForm.dataScope = "all";
  modelForm.actionRoles = normalizeActionRoles();
  modelFieldsDraft.value = [{ name: "title", label: "标题", type: "string", required: true, read_roles: [], write_roles: [], mask_roles: [] }];
  dlg.model = true;
}

function openModelEdit(row: DataModelInfo) {
  modelEditingId = row.id;
  modelForm.name = row.name;
  modelForm.isPublic = !!row.is_public;
  modelForm.rowOwnerField = row.row_owner_field || "";
  modelForm.workflowDefinitionId = row.workflow_definition_id || null;
  modelForm.dataScope = row.data_scope || "all";
  modelForm.actionRoles = normalizeActionRoles(row.action_roles || {});
  modelFieldsDraft.value = (row.fields || []).map((f: any) => ({
    ...f,
    read_roles: f.read_roles || [],
    write_roles: f.write_roles || [],
    mask_roles: f.mask_roles || [],
  }));
  dlg.model = true;
}

function onMasterDetailGenerated() {
  loadPages();
}

function onAiModelGenerated(draft: any) {
  modelEditingId = null;
  modelForm.name = draft.name;
  modelForm.isPublic = false;
  modelForm.rowOwnerField = "";
  modelForm.dataScope = "all";
  modelForm.actionRoles = normalizeActionRoles();
  modelFieldsDraft.value = (draft.fields || []).map((f: any) => ({
    ...f,
    label: f.label || f.name,
    read_roles: [],
    write_roles: [],
    mask_roles: [],
  }));
  dlg.model = true;
}

async function suggestPermissions() {
  try {
    const res = await api.post<any>("/ai/models/permissions/", {
      app_id: appId,
      model_id: modelEditingId || 0,
      fields: modelFieldsDraft.value,
    });
    modelForm.dataScope = res.data_scope || "all";
    modelForm.rowOwnerField = res.row_owner_field || "";
    for (const row of actionRoleRows) {
      const roles = res.action_roles?.[row.key];
      modelForm.actionRoles[row.key] = Array.isArray(roles) ? roles : [];
    }
    for (const field of modelFieldsDraft.value) {
      if (res.mask_fields?.[field.name]) field.mask_roles = [...res.mask_fields[field.name]];
    }
    ElMessage.success("AI 权限建议已填入，请检查后保存");
  } catch (e: any) {
    ElMessage.error(e?.message || "权限建议失败");
  }
}

async function saveModel() {
  const fields = modelFieldsDraft.value
    .map((f) => ({
      ...f,
      name: String(f.name || "").trim(),
      label: String(f.label || "").trim() || String(f.name || "").trim(),
      required: !!f.required,
      read_roles: Array.isArray(f.read_roles) ? f.read_roles : [],
      write_roles: Array.isArray(f.write_roles) ? f.write_roles : [],
      mask_roles: Array.isArray(f.mask_roles) ? f.mask_roles : [],
    }))
    .filter((f) => f.name);
  if (!fields.length) {
    ElMessage.warning("请至少添加一个字段");
    return;
  }
  const names = new Set();
  for (const f of fields) {
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(f.name)) {
      ElMessage.warning(`字段名不合法：${f.name}`);
      return;
    }
    if (names.has(f.name)) {
      ElMessage.warning(`字段名重复：${f.name}`);
      return;
    }
    names.add(f.name);
  }
  saving.value = true;
  try {
    const body = {
      name: modelForm.name,
      fields,
      is_public: modelForm.isPublic,
      row_owner_field: modelForm.dataScope === "owner" ? modelForm.rowOwnerField : "",
      workflow_definition_id: modelForm.workflowDefinitionId,
      data_scope: modelForm.dataScope,
      action_roles: modelForm.actionRoles,
    };
    if (modelEditingId === null) {
      await api.post(`/apps/${appId.value}/models/`, body);
      ElMessage.success("模型已创建");
    } else {
      await api.put(`/models/${modelEditingId}/`, body);
      ElMessage.success("模型已保存");
    }
    dlg.model = false;
    loadModels();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "保存失败");
  } finally {
    saving.value = false;
  }
}

async function openModelDetail(row: DataModelInfo) {
  try {
    const detail = await api.get<DataModelInfo>(`/models/${row.id}/`);
    modelDetailFields.value = (detail.fields || []).map((f) => ({ ...f, description: (f as any).description }));
    dlg.modelDetail = true;
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "加载模型失败");
  }
}

async function deleteModel(row: DataModelInfo) {
  try {
    await ElMessageBox.confirm(`确定删除模型「${row.name}」吗？`, "提示", { type: "warning" });
  } catch {
    return;
  }
  try {
    await api.del(`/models/${row.id}/`);
    ElMessage.success("已删除");
    loadModels();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "删除失败");
  }
}

// ============ 成员 ============
async function loadMembers() {
  loadingMembers.value = true;
  try {
    const data = await api.get<unknown>(`/apps/${appId.value}/members/`);
    members.value = asList<AppMember>(data);
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "加载成员失败");
  } finally {
    loadingMembers.value = false;
  }
}

function openMemberCreate() {
  memberForm.user_id = 1;
  memberForm.role = "editor";
  dlg.member = true;
}

async function createMember() {
  saving.value = true;
  try {
    await api.post(`/apps/${appId.value}/members/`, {
      user_id: memberForm.user_id,
      role: memberForm.role,
    });
    ElMessage.success("成员已添加");
    dlg.member = false;
    loadMembers();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "添加失败");
  } finally {
    saving.value = false;
  }
}

function changeRole(row: AppMember) {
  roleTarget.user_id = row.user;
  roleTarget.role = row.role;
  dlg.role = true;
}

async function saveRole() {
  saving.value = true;
  try {
    await api.put(`/apps/${appId.value}/members/${roleTarget.user_id}/`, { role: roleTarget.role });
    ElMessage.success("角色已更新");
    dlg.role = false;
    loadMembers();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "更新失败");
  } finally {
    saving.value = false;
  }
}

async function removeMember(row: AppMember) {
  try {
    await ElMessageBox.confirm(`确定移除成员「${row.username}」吗？`, "提示", { type: "warning" });
  } catch {
    return;
  }
  try {
    await api.del(`/apps/${appId.value}/members/${row.user}/`);
    ElMessage.success("已移除");
    loadMembers();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "移除失败");
  }
}

// ============ 发布 ============
async function loadReleases() {
  loadingReleases.value = true;
  try {
    const data = await api.get<unknown>(`/apps/${appId.value}/releases/?page=1&size=50`);
    releases.value = asList<ReleaseInfo>(data);
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "加载发布记录失败");
  } finally {
    loadingReleases.value = false;
  }
}

function openTraffic(row: ReleaseInfo) {
  trafficTarget.id = row.id;
  trafficTarget.ratio = row.traffic_ratio;
  dlg.traffic = true;
}

async function saveTraffic() {
  saving.value = true;
  try {
    await api.put(`/releases/${trafficTarget.id}/traffic/`, { traffic_ratio: trafficTarget.ratio });
    ElMessage.success("灰度比例已更新");
    dlg.traffic = false;
    loadReleases();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "更新失败");
  } finally {
    saving.value = false;
  }
}

async function rollbackRelease(row: ReleaseInfo) {
  try {
    await ElMessageBox.confirm(`回滚到版本 ${row.version}？将新建一个发布指向其快照。`, "提示", { type: "warning" });
  } catch {
    return;
  }
  try {
    await api.post(`/releases/${row.id}/rollback/`, {});
    ElMessage.success("已回滚");
    loadReleases();
    loadApp();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "回滚失败");
  }
}

// ============ 初始化 ============
function onTabChange(name: string | number) {
  const t = String(name);
  if (t === "pages") loadPages();
  else if (t === "datasources") loadDss();
  else if (t === "models") loadModels();
  else if (t === "members") loadMembers();
  else if (t === "releases") loadReleases();
}

function onAppMore(command: string) {
  if (command === "ops") router.push(`/admin/apps/${appId}/ops`);
  else if (command === "settings") router.push(`/admin/apps/${appId}/settings`);
  else if (command === "auth") router.push(`/admin/apps/${appId}/auth`);
  else if (command === "tokens") router.push(`/admin/apps/${appId}/design-tokens`);
  else if (command === "workflow") router.push(`/workflow/design/${appId}`);
  else if (command === "edit") openAppEdit();
  else if (command === "export") exportTemplate();
  else if (command === "clone") cloneApp();
  else if (command === "archive") archiveApp();
  else if (command === "delete") deleteApp();
}

onMounted(() => {
  loadApp();
  loadPages();
  loadModels();
  loadReleases();
  loadWorkflows();
});
</script>

<style scoped>
.wp-field-builder {
  width: 100%;
  max-height: 360px;
  overflow: auto;
}
.wp-muted-cell {
  color: #c0c4cc;
  font-size: 12px;
}
.wp-page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 12px;
  gap: 12px;
}
.wp-page-title-block h2 {
  margin: 0;
  font-size: 18px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.wp-page-desc {
  margin: 6px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.wp-page-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
.wp-tab-toolbar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.wp-dialog-hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin: 0;
}
.app-detail-stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }
.app-detail-stat { display: flex; flex-direction: column; align-items: flex-start; gap: 3px; padding: 14px 16px; border: 1px solid #e8edf5; border-radius: 12px; background: #fff; text-align: left; cursor: pointer; transition: border-color 0.16s ease, box-shadow 0.16s ease; }
.app-detail-stat:hover { border-color: #bfdbfe; box-shadow: 0 8px 20px rgba(37, 99, 235, 0.08); }
.app-detail-stat.is-static { cursor: default; }
.app-detail-stat span { color: #64748b; font-size: 11px; }
.app-detail-stat strong { color: #0f172a; font-size: 24px; line-height: 1.2; }
.app-detail-stat small { color: #94a3b8; font-size: 10px; }
.app-detail-stat .is-status { padding-top: 4px; }
@media (max-width: 900px) { .app-detail-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
