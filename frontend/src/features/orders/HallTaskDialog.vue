<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from "vue";
import { MapPin, Package, X } from "@lucide/vue";

const props = defineProps({
  task: Object,
  demo: Boolean,
  busy: Boolean,
  error: String,
});
const emit = defineEmits(["close", "simulate"]);
const dialog = ref(null);
let previousFocus;
const money = (value) => (value / 100).toFixed(2);
watch(
  () => props.task,
  async (task) => {
    if (task) {
      if (!dialog.value?.open) previousFocus = document.activeElement;
      await nextTick();
      if (!dialog.value.open) dialog.value.showModal();
    } else if (dialog.value?.open) {
      dialog.value.close();
      previousFocus?.focus();
    }
  },
);
onBeforeUnmount(() => dialog.value?.close());
</script>
<template>
  <dialog
    ref="dialog"
    class="hall-dialog"
    aria-labelledby="hall-task-title"
    @cancel="busy ? $event.preventDefault() : emit('close')"
    @click.self="!busy && emit('close')"
  >
    <template v-if="task">
      <button
        class="icon-button close-detail"
        aria-label="关闭详情"
        :disabled="busy"
        @click="emit('close')"
      >
        <X :size="20" />
      </button>
      <span class="soft-tag"
        >{{ task.pricingSource === "demo" ? "演示订单" : "已支付" }} ·
        待接单</span
      >
      <h2 id="hall-task-title">{{ task.company }}代取需求</h2>
      <div class="detail-route">
        <p><MapPin :size="18" />{{ task.station }}</p>
        <span>送至</span>
        <p><MapPin :size="18" />{{ task.address }}</p>
      </div>
      <dl>
        <div>
          <dt>包裹规格</dt>
          <dd><Package :size="15" /> {{ task.size }} / {{ task.weight }} kg</dd>
        </div>
        <div>
          <dt>期望送达</dt>
          <dd>
            {{
              new Date(task.expectedAt).toLocaleString("zh-CN", {
                hour12: false,
              })
            }}
          </dd>
        </div>
        <div>
          <dt>基础运费</dt>
          <dd>¥{{ money(task.baseFeeCents) }}</dd>
        </div>
        <div>
          <dt>代取小费</dt>
          <dd class="detail-tip">¥{{ money(task.tipCents) }}</dd>
        </div>
        <div>
          <dt>备注</dt>
          <dd>{{ task.note || "暂无备注" }}</dd>
        </div>
      </dl>
      <p class="privacy-note">
        取件码将在接单后提供，请先确认取件点和送达位置是否顺路。
      </p>
      <div v-if="demo" class="simulate-box">
        <strong>状态演示</strong>
        <p>
          模拟其他同学接单或发布者取消，检查大厅是否及时更新；不会产生真实接单。
        </p>
        <div>
          <button
            class="outline-button"
            :disabled="busy"
            @click="emit('simulate', 'accepted')"
          >
            模拟被接单</button
          ><button
            class="outline-button"
            :disabled="busy"
            @click="emit('simulate', 'cancelled')"
          >
            模拟取消
          </button>
        </div>
      </div>
      <p v-if="error" class="dialog-error" role="alert">{{ error }}</p>
      <button
        class="primary-button close-action"
        :disabled="busy"
        @click="emit('close')"
      >
        知道了
      </button>
    </template>
  </dialog>
</template>
<style scoped>
.hall-dialog {
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 32px;
  width: min(540px, calc(100vw - 36px));
  max-height: calc(100dvh - 36px);
  overflow-y: auto;
  color: #253c36;
}
.hall-dialog::backdrop {
  background: #12322480;
  backdrop-filter: blur(4px);
}
.close-detail {
  position: absolute;
  top: 12px;
  right: 12px;
}
h2 {
  font-size: 22px;
  margin: 18px 0 22px;
}
.detail-route {
  background: #f4f8f3;
  padding: 18px;
  border-radius: 9px;
}
.detail-route p {
  display: flex;
  align-items: start;
  gap: 10px;
  font-size: 14px;
  overflow-wrap: anywhere;
}
.detail-route p svg {
  margin-top: 4px;
  color: #6f9277;
}
.detail-route > span {
  display: block;
  margin: 7px 0 7px 28px;
  font-size: 11px;
  color: #728475;
}
dl {
  margin: 20px 0;
}
dl > div {
  display: grid;
  grid-template-columns: 82px minmax(0, 1fr);
  gap: 12px;
  padding: 12px 0;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
  line-height: 1.8;
}
dt {
  color: #718174;
}
dd {
  margin: 0;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}
.detail-tip {
  color: #a77a47;
  font-weight: 650;
}
.privacy-note,
.simulate-box p {
  font-size: 12px;
  color: #647a69;
}
.simulate-box {
  background: #f4f7f2;
  border: 1px solid #e3eadd;
  border-radius: 9px;
  padding: 15px;
  margin-top: 18px;
}
.simulate-box strong {
  font-size: 12px;
}
.simulate-box p {
  margin: 8px 0 12px;
}
.simulate-box > div {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.close-action {
  margin-top: 22px;
}
.dialog-error {
  color: #a33d32;
  font-size: 12px;
  margin-top: 16px;
}
@media (max-width: 640px) {
  .hall-dialog {
    padding: 24px;
  }
}
</style>
