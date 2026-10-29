<script setup>
import { reactive, ref } from "vue";
import PageHeading from "../../components/PageHeading.vue";
const draft = reactive({
  company: "",
  code: "",
  station: "",
  address: "",
  size: "小件",
  tip: "",
  time: "",
  note: "",
});
const message = ref("");
</script>
<template>
  <PageHeading
    title="把取件这件事，交给顺路的同学"
    subtitle="填写取件信息，让每一份托付都清楚明白。"
    eyebrow="NEW REQUEST"
  />
  <div class="notice">
    发布需求需要登录并通过学生认证。当前表单仅供界面预览，不保存取件码，不生成订单。
  </div>
  <form
    class="panel form-panel"
    @submit.prevent="
      message = '表单校验通过。订单与支付服务接入后才能发布，当前未生成订单。'
    "
  >
    <h2>取件信息</h2>
    <div class="form-grid">
      <label
        >快递公司<input
          v-model="draft.company"
          required
          maxlength="30"
          placeholder="例如：中通快递" /></label
      ><label
        >取件点<select v-model="draft.station" required>
          <option value="" disabled>请选择取件点</option>
          <option>菜鸟驿站</option>
          <option>顺丰服务点</option>
        </select></label
      ><label
        >取件码<input
          v-model="draft.code"
          required
          maxlength="50"
          placeholder="请填写完整取件码" /></label
      ><label
        >包裹规格<select v-model="draft.size">
          <option>小件</option>
          <option>中件</option>
          <option>大件</option>
        </select></label
      ><label
        >送达地址<input
          v-model="draft.address"
          required
          maxlength="100"
          placeholder="宿舍楼及门牌号" /></label
      ><label
        >期望送达时间<input
          v-model="draft.time"
          type="datetime-local"
          required /></label
      ><label
        >小费金额（元）<input
          v-model="draft.tip"
          type="number"
          min="0"
          max="999"
          step="0.01"
          required
          placeholder="0.00" /></label
      ><label
        >备注<input
          v-model="draft.note"
          maxlength="200"
          placeholder="还有什么需要告诉同学的？"
      /></label>
    </div>
    <div class="form-actions">
      <button class="primary-button" type="submit">预览发布信息</button>
      <p v-if="message" role="status">{{ message }}</p>
    </div>
  </form>
</template>
