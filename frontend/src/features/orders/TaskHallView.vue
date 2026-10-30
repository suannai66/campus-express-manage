<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { RefreshCw, SlidersHorizontal } from "@lucide/vue";
import PageHeading from "../../components/PageHeading.vue";
import TaskCard from "../../components/TaskCard.vue";
import EmptyState from "../../components/EmptyState.vue";
import HallTaskDialog from "./HallTaskDialog.vue";
import { orderApi } from "./api";

const route = useRoute(),
  router = useRouter();
const emptyFilters = () => ({
  station: "",
  address: "",
  tipMin: "",
  tipMax: "",
  expectedFrom: "",
  expectedTo: "",
});
const filters = reactive(emptyFilters());
const context = ref(null),
  rows = ref([]),
  stations = ref([]),
  total = ref(0),
  page = ref(1);
const loading = ref(true),
  refreshing = ref(false),
  busy = ref(false),
  error = ref("");
const filterError = ref(""),
  message = ref(""),
  selected = ref(null),
  dialogError = ref("");
const selectedLoading = ref(""),
  lastUpdated = ref(null);
const pageSize = 12;
const applied = ref({});
let generation = 0,
  detailGeneration = 0,
  timer,
  disposed = false;
const pageCount = computed(() =>
  Math.max(1, Math.ceil(total.value / pageSize)),
);
const tasks = computed(() =>
  rows.value.map((order, index) => ({
    id: order.orderId,
    station: order.station,
    building: order.address,
    size: order.size,
    reward: order.tipCents / 100,
    time:
      new Date(order.expectedAt).toLocaleString("zh-CN", {
        month: "numeric",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }) + "前送达",
    company: order.company,
    initials: [...order.company][0],
    color: ["peach", "mint", "lavender"][index % 3],
    live: true,
    demo: order.pricingSource === "demo",
  })),
);
const demoState = computed(() =>
  !context.value?.user
    ? "guest"
    : context.value.verified
      ? "verified"
      : "unverified",
);
const appliedCount = computed(() => Object.keys(applied.value).length);

function closeDetail() {
  detailGeneration++;
  selected.value = null;
  selectedLoading.value = "";
  dialogError.value = "";
}
async function loadTasks(background = false) {
  const version = ++generation;
  if (!context.value?.user) {
    rows.value = [];
    total.value = 0;
    lastUpdated.value = null;
    loading.value = false;
    refreshing.value = false;
    return;
  }
  loading.value = !background;
  refreshing.value = true;
  try {
    const data = await orderApi.hall({
      ...applied.value,
      page: page.value,
      pageSize,
    });
    if (version !== generation) return;
    const lastPage = Math.max(1, Math.ceil(data.total / pageSize));
    if (page.value > lastPage) {
      page.value = lastPage;
      await loadTasks(background);
      return;
    }
    rows.value = data.items;
    total.value = data.total;
    stations.value = data.stations;
    lastUpdated.value = new Date();
    error.value = "";
    if (selected.value && !busy.value) {
      const id = selected.value.orderId,
        detailVersion = detailGeneration;
      try {
        const detail = await orderApi.hallDetail(id);
        if (version === generation && detailVersion === detailGeneration)
          selected.value = detail;
      } catch (cause) {
        if (version !== generation || detailVersion !== detailGeneration)
          return;
        if ([404, 409].includes(cause.status)) {
          closeDetail();
          message.value = "这份任务已被接单或取消，大厅已更新。";
        } else {
          dialogError.value = "暂时无法核对任务状态，请稍后重试。";
        }
      }
    }
  } catch (cause) {
    if (version !== generation) return;
    error.value =
      cause.status === 401
        ? "登录已失效，请重新登录后浏览任务。"
        : cause.message;
  } finally {
    if (version === generation) {
      loading.value = false;
      refreshing.value = false;
    }
  }
}

async function initialize() {
  error.value = "";
  loading.value = true;
  try {
    context.value = await orderApi.context();
    if (!context.value.user && context.value.mode === "external") {
      await router.replace({
        path: "/login",
        query: { redirect: route.fullPath },
      });
      return;
    }
    await loadTasks();
  } catch (cause) {
    error.value = cause.message;
    loading.value = false;
  }
}

async function applyFilters() {
  const next = {};
  filterError.value = "";
  if (filters.station) next.station = filters.station;
  if (filters.address.trim()) next.address = filters.address.trim();
  for (const key of ["tipMin", "tipMax"]) {
    if (filters[key] !== "") {
      if (
        !/^\d+(\.\d{1,2})?$/.test(String(filters[key])) ||
        Number(filters[key]) > 999
      ) {
        filterError.value = "小费范围请输入 0 至 999 元，最多两位小数。";
        return;
      }
      next[key + "Cents"] = Math.round(Number(filters[key]) * 100);
    }
  }
  if (
    next.tipMinCents !== undefined &&
    next.tipMaxCents !== undefined &&
    next.tipMinCents > next.tipMaxCents
  ) {
    filterError.value = "小费下限不能大于上限。";
    return;
  }
  for (const key of ["expectedFrom", "expectedTo"]) {
    if (filters[key]) {
      const date = new Date(filters[key]);
      if (!Number.isFinite(date.getTime())) {
        filterError.value = "请选择有效的送达时间。";
        return;
      }
      next[key] = date.toISOString();
    }
  }
  if (
    next.expectedFrom &&
    next.expectedTo &&
    next.expectedFrom > next.expectedTo
  ) {
    filterError.value = "开始时间不能晚于结束时间。";
    return;
  }
  applied.value = next;
  page.value = 1;
  message.value = "";
  closeDetail();
  await loadTasks();
}
async function resetFilters() {
  Object.assign(filters, emptyFilters());
  await applyFilters();
}
async function changePage(value) {
  page.value = value;
  await loadTasks();
}
async function showDetail(task) {
  const version = ++detailGeneration;
  selectedLoading.value = task.id;
  dialogError.value = "";
  message.value = "";
  try {
    const detail = await orderApi.hallDetail(task.id);
    if (version === detailGeneration) selected.value = detail;
  } catch (cause) {
    if (version !== detailGeneration) return;
    message.value = cause.message;
    await loadTasks(true);
  } finally {
    if (version === detailGeneration) selectedLoading.value = "";
  }
}
async function seedDemo() {
  busy.value = true;
  message.value = "";
  try {
    const result = await orderApi.seedHall();
    message.value = result.created
      ? `已添加 ${result.created} 条演示订单。`
      : "今日演示任务已添加，已移出的任务不会重新开放。";
    await loadTasks();
  } catch (cause) {
    error.value = cause.message;
  } finally {
    busy.value = false;
  }
}
async function switchDemo(event) {
  busy.value = true;
  closeDetail();
  generation++;
  try {
    await orderApi.demoSession(event.target.value);
    page.value = 1;
    await initialize();
  } catch (cause) {
    error.value = cause.message;
  } finally {
    busy.value = false;
  }
}
async function simulate(status) {
  if (busy.value || !selected.value) return;
  busy.value = true;
  dialogError.value = "";
  try {
    await orderApi.demoStatus(selected.value.orderId, status);
    closeDetail();
    message.value =
      status === "accepted"
        ? "已模拟被接单，任务已从大厅移除。"
        : "已模拟取消，任务已从大厅移除。";
    await loadTasks(true);
  } catch (cause) {
    dialogError.value = cause.message;
  } finally {
    busy.value = false;
  }
}
function refreshVisible() {
  if (!document.hidden && !busy.value && !refreshing.value) loadTasks(true);
}
onMounted(async () => {
  document.addEventListener("visibilitychange", refreshVisible);
  await initialize();
  if (!disposed) timer = setInterval(refreshVisible, 10000);
});
onBeforeUnmount(() => {
  disposed = true;
  generation++;
  detailGeneration++;
  clearInterval(timer);
  document.removeEventListener("visibilitychange", refreshVisible);
});
</script>

<template>
  <PageHeading
    title="顺路带一件，温暖多一点"
    subtitle="发现校园里的代取需求，找到属于你的顺路任务。"
    eyebrow="TASK HALL"
  />
  <div v-if="context?.mode === 'demo'" class="hall-demo">
    <div>
      <strong>演示模式</strong>
      <p>
        展示数据库中的演示订单，不产生真实接单。自己发布的需求不会出现在接单列表。
      </p>
    </div>
    <div class="demo-actions">
      <label
        >体验身份<select
          :value="demoState"
          :disabled="busy"
          @change="switchDemo"
        >
          <option value="verified">已认证同学</option>
          <option value="unverified">未认证同学</option>
          <option value="guest">未登录访客</option>
        </select></label
      ><button
        class="outline-button"
        :disabled="busy || !context.user"
        @click="seedDemo"
      >
        {{ busy ? "正在处理…" : "添加演示任务" }}
      </button>
    </div>
  </div>
  <div v-if="context && !context.user" class="notice">
    登录后，即可浏览代取需求。<RouterLink
      class="text-button"
      to="/login?redirect=%2Ftasks"
      >去登录</RouterLink
    >
  </div>
  <form class="panel hall-filters" @submit.prevent="applyFilters">
    <div class="filter-title">
      <SlidersHorizontal :size="18" />
      <h2>找到顺路的任务</h2>
      <span>按期望送达时间排序</span>
    </div>
    <fieldset :disabled="!context?.user || busy">
      <div class="filter-grid">
        <label
          >取件点<select v-model="filters.station">
            <option value="">全部取件点</option>
            <option
              v-if="filters.station && !stations.includes(filters.station)"
            >
              {{ filters.station }}
            </option>
            <option v-for="station in stations" :key="station">
              {{ station }}
            </option>
          </select></label
        >
        <label
          >送达地址<input
            v-model="filters.address"
            maxlength="200"
            placeholder="例如：实验楼、图书馆、饭堂"
        /></label>
        <div class="tip-filter">
          <label
            >小费下限（元）<input
              v-model="filters.tipMin"
              type="number"
              min="0"
              max="999"
              step="0.01"
              placeholder="不限" /></label
          ><span>至</span
          ><label
            >小费上限（元）<input
              v-model="filters.tipMax"
              type="number"
              min="0"
              max="999"
              step="0.01"
              placeholder="不限"
          /></label>
        </div>
        <label
          >送达时间从<input
            v-model="filters.expectedFrom"
            type="datetime-local" /></label
        ><label
          >送达时间至<input v-model="filters.expectedTo" type="datetime-local"
        /></label>
        <div class="filter-actions">
          <button class="text-button" type="button" @click="resetFilters">
            重置筛选</button
          ><button class="primary-button" type="submit">筛选任务</button>
        </div>
      </div>
      <p v-if="filterError" class="filter-error" role="alert">
        {{ filterError }}
      </p>
    </fieldset>
  </form>
  <div class="hall-summary">
    <div>
      <h2>
        待接单任务
        <span v-if="!error && context?.user && !loading" class="soft-tag"
          >{{ total }} 条</span
        >
      </h2>
      <p>
        仅展示已支付的待接单需求，不包含自己发布的订单。<span
          v-if="appliedCount"
          >已应用 {{ appliedCount }} 项筛选。</span
        >
      </p>
    </div>
    <button
      class="text-button refresh-button"
      :disabled="refreshing || !context?.user"
      @click="loadTasks(true)"
    >
      <RefreshCw :size="14" />{{ refreshing ? "正在更新…" : "刷新任务" }}
    </button>
  </div>
  <p v-if="lastUpdated && !error" class="refresh-info">
    每 10 秒自动更新 · 最近更新
    {{ lastUpdated.toLocaleTimeString("zh-CN", { hour12: false }) }}
  </p>
  <p v-if="message" class="hall-message" role="status">{{ message }}</p>
  <div v-if="error" class="panel hall-error" role="alert">
    <h3>暂时无法获取任务</h3>
    <p>{{ error }}</p>
    <button class="outline-button" @click="initialize">重新加载</button
    ><RouterLink
      v-if="context?.user"
      class="text-button"
      to="/login?redirect=%2Ftasks"
      >重新登录</RouterLink
    >
  </div>
  <div v-else-if="loading" class="panel loading-state" role="status">
    正在寻找顺路的任务…
  </div>
  <div
    v-else-if="context?.user && tasks.length"
    class="task-grid hall-grid"
    :aria-busy="refreshing"
  >
    <TaskCard
      v-for="task in tasks"
      :key="task.id"
      :task="task"
      @details="showDetail"
    />
  </div>
  <EmptyState
    v-else-if="context?.user"
    class="panel"
    title="暂时没有匹配的任务"
    description="试试其他取件点、送达地址，或放宽小费与时间范围。"
    ><button class="outline-button" @click="resetFilters">
      清除筛选
    </button></EmptyState
  >
  <p v-if="selectedLoading" class="refresh-info" role="status">
    正在读取任务详情…
  </p>
  <nav
    v-if="!error && total > pageSize"
    class="hall-pagination"
    aria-label="任务分页"
  >
    <button
      class="outline-button"
      :disabled="page <= 1 || refreshing"
      @click="changePage(page - 1)"
    >
      上一页</button
    ><span>第 {{ page }} / {{ pageCount }} 页</span
    ><button
      class="outline-button"
      :disabled="page >= pageCount || refreshing"
      @click="changePage(page + 1)"
    >
      下一页
    </button>
  </nav>
  <HallTaskDialog
    :task="selected"
    :demo="context?.mode === 'demo'"
    :busy="busy"
    :error="dialogError"
    @close="closeDetail"
    @simulate="simulate"
  />
</template>

<style scoped>
.hall-demo {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
  background: #edf4ef;
  border: 1px solid #dce8df;
  border-radius: 9px;
  padding: 16px 20px;
  margin-bottom: 22px;
}
.hall-demo strong {
  font-size: 12px;
  color: #234f41;
}
.hall-demo p {
  font-size: 12px;
  color: #59725f;
  margin-top: 5px;
}
.demo-actions {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-shrink: 0;
}
.demo-actions label {
  font-size: 11px;
}
.demo-actions select {
  margin-top: 5px;
  padding: 7px 9px;
}
.hall-filters {
  padding: 24px;
}
.filter-title {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-bottom: 22px;
}
.filter-title h2 {
  font-size: 16px;
}
.filter-title > span {
  margin-left: auto;
  font-size: 11px;
  color: #738275;
}
fieldset {
  border: 0;
  padding: 0;
  margin: 0;
  min-width: 0;
}
fieldset:disabled {
  opacity: 0.6;
}
.filter-grid {
  display: grid;
  grid-template-columns: 1fr 1.2fr 1.2fr;
  gap: 22px;
}
.tip-filter {
  display: flex;
  align-items: end;
  gap: 9px;
  min-width: 0;
}
.tip-filter label {
  flex: 1;
  min-width: 0;
}
.tip-filter > span {
  padding-bottom: 14px;
  font-size: 11px;
  color: #829081;
}
.filter-actions {
  display: flex;
  justify-content: end;
  align-items: end;
  gap: 20px;
}
.filter-actions .text-button {
  padding: 12px 0;
}
.filter-error {
  color: #a33d32;
  font-size: 12px;
  margin-top: 15px;
}
.hall-summary {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 15px;
  margin: 30px 0 8px;
}
.hall-summary h2 {
  font-size: 18px;
}
.hall-summary .soft-tag {
  vertical-align: middle;
  margin-left: 8px;
}
.hall-summary p {
  margin-top: 8px;
  font-size: 12px;
  color: #6d7f71;
}
.refresh-button {
  display: flex;
  gap: 7px;
  align-items: center;
}
.refresh-info {
  color: #728174;
  font-size: 11px;
  margin: 10px 0 18px;
}
.hall-grid {
  margin-top: 20px;
}
.hall-grid :deep(.task-route p) {
  overflow-wrap: anywhere;
}
.hall-grid :deep(.task-route p > svg),
.hall-grid :deep(.destination-dot) {
  flex-shrink: 0;
}
.hall-grid :deep(.task-meta) {
  gap: 10px;
}
.hall-grid :deep(.task-meta > span:last-child) {
  white-space: nowrap;
}
.hall-message {
  background: #edf4ef;
  border: 1px solid #dce8df;
  padding: 13px 17px;
  border-radius: 9px;
  margin: 16px 0;
  font-size: 12px;
  color: #426b50;
}
.hall-error,
.loading-state {
  padding: 35px 24px;
  margin-top: 20px;
}
.hall-error h3 {
  color: #a33d32;
}
.hall-error p {
  font-size: 12px;
  color: #6d7f71;
  margin: 12px 0 18px;
}
.hall-error .text-button {
  margin-left: 18px;
}
.loading-state {
  text-align: center;
  font-size: 13px;
  color: #6d7f71;
}
.hall-pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 20px;
  margin: 30px 0 10px;
}
.hall-pagination > span {
  font-size: 12px;
  color: #6d7f71;
}
@media (max-width: 1100px) {
  .hall-demo {
    flex-wrap: wrap;
  }
  .filter-grid {
    grid-template-columns: 1fr 1fr;
  }
  .tip-filter {
    grid-column: 1 / -1;
    max-width: 460px;
  }
  .filter-actions {
    grid-column: 1 / -1;
  }
}
@media (max-width: 640px) {
  .hall-filters {
    padding: 20px;
  }
  .filter-grid {
    grid-template-columns: minmax(0, 1fr);
    gap: 18px;
  }
  .tip-filter {
    max-width: none;
  }
  .filter-title {
    flex-wrap: wrap;
  }
  .filter-title > span {
    margin-left: 0;
    width: 100%;
  }
  .hall-summary {
    align-items: start;
  }
  .hall-summary p {
    max-width: 240px;
  }
  .demo-actions {
    width: 100%;
    justify-content: space-between;
    flex-wrap: wrap;
  }
  .filter-actions {
    justify-content: space-between;
  }
}
</style>
