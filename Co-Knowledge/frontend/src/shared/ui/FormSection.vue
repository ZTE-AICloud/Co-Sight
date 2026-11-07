<template><section class="studio-form-section"><div class="studio-section-heading"><span class="studio-section-number text-caption">{{ number }}</span><h3 class="text-section-title">{{ title }}</h3><span v-if="note" class="studio-section-note text-caption">{{ note }}</span></div><slot/></section></template>
<script setup>
defineProps({ number: String, title: String, note: String })
</script>
