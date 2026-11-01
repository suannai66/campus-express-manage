<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { fulfillmentApi as api, formatTime } from "./api";
const props = defineProps({ orderId: String, uid: String, revision: Number });
const emit = defineEmits(["submitted"]);
const records = ref([]),
  reviewable = ref(false),
  loaded = ref(false),
  busy = ref(false),
  loadError = ref(""),
  error = ref("");
const rating = ref(5),
  tags = ref([]),
  comment = ref("");
const choices = ["准时送达", "沟通顺畅", "包裹完好", "态度友好", "有待改进"];
const mine = computed(() =>
  records.value.some((item) => item.reviewerUid === props.uid),
);
let generation = 0;
async function load() {
  const current = ++generation;
  try {
    const result = await api.reviews(props.orderId);
    if (current !== generation) return;
    records.value = result.items;
    reviewable.value = result.reviewable;
    loaded.value = true;
    loadError.value = "";
  } catch (e) {
    if (current === generation) loadError.value = e.message;
  }
}
async function submit() {
  busy.value = true;
  error.value = "";
  try {
    await api.review(props.orderId, {
      rating: rating.value,
      tags: tags.value,
      comment: comment.value.trim(),
    });
    emit("submitted");
  } catch (e) {
    error.value =
      e.status === 409 ? e.message : `${e.message}。请刷新确认评价是否已提交。`;
  } finally {
    await load();
    busy.value = false;
  }
}
watch(() => [props.orderId, props.revision], load, { immediate: true });
onBeforeUnmount(() => {
  generation++;
});
</script>
<template>
  <section class="reviews" aria-label="订单评价">
    <h3>双向评价</h3>
    <p v-if="loadError || error" role="alert" class="error">
      {{ loadError || error }}
    </p>
    <button type="button" class="text-button" @click="load">刷新评价</button>
    <p v-if="!loaded && !loadError">正在加载评价…</p>
    <article v-for="item in records" :key="item.reviewId" class="review">
      <strong
        >{{ item.reviewerUid === uid ? "我的评价" : "对方的评价" }} ·
        {{ item.rating }} / 5 星</strong
      >
      <p v-if="item.tags.length">{{ item.tags.join(" · ") }}</p>
      <p class="comment">{{ item.comment || "未填写文字评价" }}</p>
      <small>{{ formatTime(item.createdAt) }}</small>
    </article>
    <p v-if="loaded && mine" role="status">
      评价已提交，不可修改。等待彼此的下一次信任。
    </p>
    <p v-else-if="loaded && !reviewable">
      送达结果确认中，评价入口将自动更新。
    </p>
    <form v-else-if="loaded" @submit.prevent="submit">
      <label
        >评分
        <select v-model="rating" :disabled="busy">
          <option v-for="n in 5" :key="n" :value="n">{{ n }} 星</option>
        </select>
      </label>
      <fieldset :disabled="busy">
        <legend>评价标签（可选，最多 5 项）</legend>
        <label v-for="tag in choices" :key="tag" class="tag"
          ><input v-model="tags" type="checkbox" :value="tag" />{{ tag }}</label
        >
      </fieldset>
      <label
        >文字评价（可选）<textarea
          v-model="comment"
          maxlength="500"
          rows="3"
          :disabled="busy"
          placeholder="分享本次互助体验"
        />
      </label>
      <small>{{ comment.length }} / 500 · 提交后不可修改</small>
      <button class="primary-button" :disabled="busy">
        {{ busy ? "提交中…" : "提交评价" }}
      </button>
    </form>
  </section>
</template>
<style scoped>
.reviews {
  border-top: 1px solid #e3e8e4;
  margin-top: 24px;
  padding-top: 12px;
}
.review {
  padding: 16px;
  background: #f4f7f3;
  border-radius: 12px;
  margin: 12px 0;
}
.comment {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
form {
  display: grid;
  gap: 12px;
  max-width: 620px;
}
label {
  display: grid;
  gap: 6px;
}
select,
textarea {
  padding: 10px;
  border: 1px solid #cdd8ce;
  border-radius: 8px;
  font: inherit;
  width: 100%;
}
fieldset {
  border: 1px solid #dde4de;
  border-radius: 8px;
  padding: 12px;
}
.tag {
  display: inline-flex;
  align-items: center;
  margin: 6px 16px 6px 0;
  gap: 6px;
}
.error {
  color: #a3342b;
}
small {
  color: #66766a;
}
.text-button {
  background: none;
  border: 0;
  color: #346844;
  cursor: pointer;
  padding: 8px 0;
}
</style>
