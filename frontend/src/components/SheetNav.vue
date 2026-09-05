<template>
  <div class="sheet" v-if="items.length">
    <button
      v-for="it in items"
      :key="it.slug"
      class="sheet-n"
      type="button"
      :class="{ on: it.slug === current, saved: it.saved && it.slug !== current }"
      :title="'第 ' + it.n + ' 题'"
      @click="$emit('pick', it.slug)"
    >
      {{ it.n }}
    </button>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  items: { n: number; slug: string; saved?: boolean }[];
  current?: string;
}>();
defineEmits<{ pick: [slug: string] }>();
</script>
