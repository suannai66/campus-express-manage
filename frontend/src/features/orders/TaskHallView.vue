<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { RefreshCw, SlidersHorizontal } from "@lucide/vue";
import PageHeading from "../../components/PageHeading.vue";
import TaskCard from "../../components/TaskCard.vue";
import EmptyState from "../../components/EmptyState.vue";
import HallTaskDialog from "./HallTaskDialog.vue";
import { orderApi, sizeLabels, formatTime } from "./api";
const router = useRouter();
const emptyFilters = () => ({
  stationId: "",
  deliveryAreaId: "",
  tipMin: "",
  tipMax: "",
  expectedFrom: "",
  expectedTo: "",
});
const filters = reactive(emptyFilters()),
  applied = ref({});
const context = ref(null),
  rows = ref([]),
  locations = ref({ stations: [], deliveryAreas: [] }),
  total = ref(0),
  page = ref(1),
  loading = ref(true),
  refreshing = ref(false),
  busy = ref(false),
  error = ref(""),
  filterError = ref(""),
  message = ref(""),
  selected = ref(null),
  dialogError = ref(""),
  lastUpdated = ref(null);
const pageSize = 20,
  pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize)));
let generation = 0,
  timer,
  disposed = false,
  acceptKey = "";
const tasks = computed(() =>
  rows.value.map((order, index) => ({
    id: order.orderId,
    station: order.stationName,
    building: order.deliveryAreaName,
    size: sizeLabels[order.size],
    amount: order.amount,
    baseFee: order.baseFee,
    tip: order.tip,
    time: formatTime(order.expectedAt) + "前送达",
    company: order.company,
    initials: [...order.company][0],
    color: ["peach", "mint", "lavender"][index % 3],
    live: true,
    demo: order.demo,
  })),
);
function closeDetail() {
  selected.value = null;
  dialogError.value = "";
  acceptKey = "";
}
async function loadTasks(background = false) {
  if (!context.value?.user || disposed || refreshing.value) return;
  const version = ++generation;
  loading.value = !background;
  refreshing.value = true;
  try {
    const data = await orderApi.hall({
      ...applied.value,
      page: page.value,
      pageSize,
    });
    if (disposed || version !== generation) return;
    const last = Math.max(1, Math.ceil(data.total / pageSize));
    if (page.value > last) {
      page.value = last;
      refreshing.value = false;
      await loadTasks(background);
      return;
    }
    rows.value = data.items;
    total.value = data.total;
    lastUpdated.value = new Date();
    error.value = "";
    if (selected.value && !busy.value) {
      const fresh = data.items.find(
        (item) => item.orderId === selected.value.orderId,
      );
      if (fresh) selected.value = fresh;
      else {
        closeDetail();
        message.value = "任务列表已更新，请重新选择任务。";
      }
    }
  } catch (cause) {
    if (!disposed && version === generation) error.value = cause.message;
  } finally {
    if (version === generation) {
      loading.value = false;
      refreshing.value = false;
    }
  }
}
async function initialize() {
  loading.value = true;
  error.value = "";
  try {
    const [identity, directory] = await Promise.all([
      orderApi.current(),
      orderApi.locations(),
    ]);
    if (disposed) return;
    context.value = { user: identity };
    locations.value = directory;
    await loadTasks();
  } catch (cause) {
    if (!disposed) error.value = cause.message;
  } finally {
    if (!disposed) loading.value = false;
  }
}
async function applyFilters() {
  if (refreshing.value) return;
  const next = {};
  filterError.value = "";
  for (const key of ["stationId", "deliveryAreaId"])
    if (filters[key]) next[key] = filters[key];
  for (const key of ["tipMin", "tipMax"])
    if (filters[key] !== "") {
      if (
        !/^\d+(\.\d{1,2})?$/.test(String(filters[key])) ||
        Number(filters[key]) > 999
      ) {
        filterError.value = "小费范围请输入 0 至 999 元，最多两位小数。";
        return;
      }
      next[key] = Math.round(Number(filters[key]) * 100);
    }
  if (
    next.tipMin !== undefined &&
    next.tipMax !== undefined &&
    next.tipMin > next.tipMax
  ) {
    filterError.value = "小费下限不能大于上限。";
    return;
  }
  for (const key of ["expectedFrom", "expectedTo"])
    if (filters[key]) {
      const value = filters[key],
        date = new Date(`${value}${value.length === 16 ? ":00" : ""}+08:00`);
      if (!Number.isFinite(date.getTime())) {
        filterError.value = "请选择有效的送达时间。";
        return;
      }
      next[key] = date.toISOString();
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
  if (refreshing.value) return;
  page.value = value;
  closeDetail();
  await loadTasks();
}
function showDetail(task) {
  selected.value = rows.value.find((row) => row.orderId === task.id);
  dialogError.value = "";
  acceptKey = crypto.randomUUID();
}
async function accept() {
  if (busy.value || !selected.value) return;
  busy.value = true;
  dialogError.value = "";
  try {
    await orderApi.accept(
      selected.value.orderId,
      selected.value.version,
      acceptKey,
    );
    closeDetail();
    message.value = "接单成功，可到我的订单查看取件信息。";
    await loadTasks(true);
  } catch (cause) {
    dialogError.value = cause.message;
    if (cause.code === "VERIFICATION_REQUIRED") {
      closeDetail();
      await router.push("/verification?redirect=%2Ftasks");
    } else if (cause.status === 409) {
      closeDetail();
      message.value = cause.message;
      await loadTasks(true);
    }
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
  <form class="panel hall-filters" @submit.prevent="applyFilters">
    <div class="filter-title">
      <SlidersHorizontal :size="18" />
      <h2>找到顺路的任务</h2>
      <span>按期望送达时间排序</span>
    </div>
    <fieldset :disabled="!context?.user || busy || refreshing">
      <div class="filter-grid">
        <label
          >取件点<select aria-label="取件点" v-model="filters.stationId">
            <option value="">全部取件点</option>
            <option
              v-for="station in locations.stations"
              :key="station.id"
              :value="station.id"
            >
              {{ station.name }}
            </option>
          </select></label
        >
        <label
          >送达区域<select
            aria-label="送达区域"
            v-model="filters.deliveryAreaId"
          >
            <option value="">全部送达区域</option>
            <option
              v-for="area in locations.deliveryAreas"
              :key="area.id"
              :value="area.id"
            >
              {{ area.name }}
            </option>
          </select></label
        >
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
        <span v-if="!error && !loading && context?.user" class="soft-tag"
          >{{ total }} 条</span
        >
      </h2>
      <p>
        仅展示已支付、未超过期望送达时间的待接单需求，不包含自己发布的订单。时间按北京时间（UTC+8）显示。
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
    {{
      lastUpdated.toLocaleTimeString("zh-CN", {
        timeZone: "Asia/Shanghai",
        hour12: false,
      })
    }}
  </p>
  <p v-if="message" class="hall-message" role="status">
    {{ message }}
    <RouterLink
      v-if="message.includes('接单成功')"
      class="text-button"
      to="/orders"
      >查看我的订单</RouterLink
    >
  </p>
  <div v-if="error" class="panel hall-error" role="alert">
    <h3>暂时无法获取任务</h3>
    <p>{{ error }}</p>
    <button class="outline-button" @click="initialize">重新加载</button>
  </div>
  <div v-else-if="loading" class="panel loading-state" role="status">
    正在寻找顺路的任务…
  </div>
  <div
    v-else-if="tasks.length"
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
    description="试试其他取件点、送达区域，或放宽小费与时间范围。"
    ><button class="outline-button" @click="resetFilters">
      清除筛选
    </button></EmptyState
  >
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
    :busy="busy"
    :error="dialogError"
    @close="closeDetail"
    @accept="accept"
  />
</template>
<style scoped>
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
