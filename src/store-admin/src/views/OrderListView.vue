<template>
  <div class="order-list" v-if="hasOrders">
    <table>
      <thead>
        <tr>
          <th>Order ID</th>
          <th>Customer ID</th>
          <th>Status</th>
          <th>Total</th>
        </tr>
      </thead>
      <tr v-for="order in orders" :key="order.orderId">
        <td>
          <router-link :to="`/order/${order.orderId}`">{{ order.orderId }}</router-link>
        </td>
        <td>{{ order.customerId }}</td>
        <td>{{ order.status === 0 ? 'Pending' : 'Completed' }}</td>
        <td>{{ orderTotal(order) }}</td>
      </tr>
    </table>
  </div>
  <div class="order-list" v-else>
    <h3>No orders to process</h3>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useOrderStore } from '@/stores'
import type { Order } from '@/types'

const orderStore = useOrderStore()

const orders = computed(() => orderStore.orders)

const orderTotal = (order: Order) => {
  return order.items.reduce((total, item) => total + item.quantity * item.price, 0).toFixed(2)
}

const hasOrders = computed(() => orders.value.length > 0)
</script>

<style scoped>
a {
  color: #0000ff;
  text-decoration: underline;
}

.order-list {
  text-align: left;
}
</style>
