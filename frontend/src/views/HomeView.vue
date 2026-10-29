<script setup>
import { ref } from "vue";
import {
  ArrowUpRight,
  ArrowRight,
  Package,
  ShieldCheck,
  Clock3,
  Heart,
  Plus,
  Compass,
} from "@lucide/vue";
import PageHeading from "../components/PageHeading.vue";
import TaskCard from "../components/TaskCard.vue";
import TaskDialog from "../components/TaskDialog.vue";
import { demoTasks } from "../data/demo";
const selected = ref(null);
</script>
<template>
  <PageHeading
    title="校园生活，轻松一点"
    subtitle="取件的路不必一个人走，让顺路的同学帮你一把。"
    eyebrow="YOUR CAMPUS, CONNECTED"
    ><span class="heading-tag"
      ><span class="dot"></span>今天，也有温暖在路上</span
    ></PageHeading
  >
  <section class="hero">
    <div class="hero-copy">
      <span class="hero-badge"><span></span>把时间留给更喜欢的事</span>
      <h2>快递有人取，<br />校园好时光<span>不耽误。</span></h2>
      <p>忙着上课，还是刚好顺路？<br />发布一份需求，或带回一份小小的托付。</p>
      <div class="hero-actions">
        <RouterLink to="/publish" class="light-button"
          ><Plus :size="18" />发布代取需求</RouterLink
        ><RouterLink to="/tasks" class="hero-link"
          >去大厅看看 <ArrowUpRight :size="18"
        /></RouterLink>
      </div>
    </div>
    <div class="parcel-scene" aria-hidden="true">
      <span class="orbit orbit-one"></span><span class="orbit orbit-two"></span
      ><span class="scene-spark spark-one">✦</span
      ><span class="scene-spark spark-two">+</span>
      <div class="scene-label label-top">
        <ShieldCheck :size="17" />学生实名 · 安心互助
      </div>
      <div class="parcel parcel-back"><span></span></div>
      <div class="parcel parcel-front">
        <div class="parcel-tape"></div>
        <Package :size="46" :stroke-width="1" /><span class="parcel-sticker"
          >CAMPUS<br />WITH CARE ↗</span
        >
      </div>
      <div class="scene-label label-bottom">
        <span class="tiny-avatar">♥</span
        ><span>一份顺路，一份温暖<small>让善意在校园里传递</small></span
        ><ArrowUpRight :size="20" />
      </div>
    </div>
  </section>
  <section class="quick-grid" aria-label="快捷服务">
    <RouterLink to="/publish" class="quick-item"
      ><span class="quick-icon peach"><Plus /></span>
      <div>
        <h3>我要代取</h3>
        <p>发布需求，等候顺路的同学</p>
      </div>
      <ArrowUpRight :size="20" /></RouterLink
    ><RouterLink to="/tasks" class="quick-item"
      ><span class="quick-icon mint"><Compass /></span>
      <div>
        <h3>我来帮忙</h3>
        <p>发现顺路任务，收获一份感谢</p>
      </div>
      <ArrowUpRight :size="20" /></RouterLink
    ><RouterLink to="/verification" class="quick-item"
      ><span class="quick-icon lavender"><ShieldCheck /></span>
      <div>
        <h3>学生身份认证</h3>
        <p>认证校园身份，开启安心互助</p>
      </div>
      <ArrowUpRight :size="20"
    /></RouterLink>
  </section>
  <section>
    <div class="section-heading">
      <div>
        <h2>顺路，帮个忙 <span class="soft-tag">示例预览</span></h2>
        <p>看看校园里有哪些等待被带回的包裹</p>
      </div>
      <RouterLink to="/tasks">全部任务 <ArrowRight :size="16" /></RouterLink>
    </div>
    <div class="task-grid">
      <TaskCard
        v-for="task in demoTasks"
        :key="task.id"
        :task="task"
        @details="selected = $event"
      />
    </div>
  </section>
  <section class="steps-panel">
    <div class="steps-intro">
      <p class="eyebrow">SIMPLE & WARM</p>
      <h2>小小三步，<br />让托付更简单。</h2>
    </div>
    <div
      v-for="(step, i) in [
        {
          title: '认证身份',
          text: '完成学生认证，加入校园互助',
          icon: ShieldCheck,
        },
        {
          title: '发布或接单',
          text: '说出你的需求，发现顺路的任务',
          icon: Clock3,
        },
        {
          title: '安心送达',
          text: '确认收件，为这份温暖留下评价',
          icon: Heart,
        },
      ]"
      :key="step.title"
      class="step"
    >
      <span class="step-number">0{{ i + 1 }}</span
      ><component :is="step.icon" :size="23" />
      <h3>{{ step.title }}</h3>
      <p>{{ step.text }}</p>
    </div>
  </section>
  <TaskDialog :task="selected" @close="selected = null" />
</template>
