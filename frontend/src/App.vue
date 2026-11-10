<script setup>
import { computed } from 'vue'
import { RouterView, useRoute } from 'vue-router'
import BlankLayout from './layouts/BlankLayout.vue'
import CustomerLayout from './layouts/CustomerLayout.vue'
import StaffLayout from './layouts/StaffLayout.vue'

const route = useRoute()
const layouts = { blank: BlankLayout, customer: CustomerLayout, staff: StaffLayout }
const layout = computed(() => layouts[route.meta.layout] || BlankLayout)
</script>

<template>
  <component :is="layout">
    <RouterView />
  </component>
</template>