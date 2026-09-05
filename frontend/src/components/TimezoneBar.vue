<template>
  <select
    class="tz-select"
    :value="current"
    title="显示和填写用的时区。开考以主机时钟为准，默认北京时间。"
    @change="setDisplayZone(($event.target as HTMLSelectElement).value)"
  >
    <option v-for="z in ZONES" :key="z.id" :value="z.id">{{ z.name }}</option>
  </select>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { ZONES, displayZone, setDisplayZone } from "../timeZone";

const current = computed(() => displayZone.value);
</script>
