<template>
  <div class="studio-status text-secondary" role="status">
    <span class="status-dot" :class="tone" aria-hidden="true"/>
    <span class="studio-status-label">{{ label }}</span>
    <p v-if="description" class="studio-field-help text-caption">{{ description }}</p>
  </div>
</template>
<script setup>
defineProps({ label: { type: String, required: true }, description: String,
  tone: { type: String, default: 'muted', validator: value => ['success','warning','danger','muted'].includes(value) } })
</script>
