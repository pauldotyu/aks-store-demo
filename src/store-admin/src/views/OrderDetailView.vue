<template>
  <div class="order-detail" v-if="orderExists">
    <div class="action-button">
      <button @click="completeOrder" class="button">Complete Order</button>
    </div>
    <br />
    <div class="order-header">
      <p><b>Order ID:</b> {{ order?.orderId }}</p>
      <p><b>Customer ID:</b> {{ order?.customerId }}</p>
      <p><b>Status:</b> {{ order?.status === 0 ? 'Pending' : 'Completed' }}</p>
    </div>
    <div class="order-items">
      <table>
        <thead>
          <tr>
            <th>Product ID</th>
            <th>Product Name</th>
            <th>Quantity</th>
            <th>Price</th>
            <th>Total</th>
          </tr>
        </thead>
        <tr v-for="item in order?.items" :key="item.productId">
          <td>
            <router-link :to="`/product/${item.productId}`">{{ item.productId }}</router-link>
          </td>
          <td>{{ productLookup(item.productId) }}</td>
          <td>{{ item.quantity }}</td>
          <td>{{ item.price.toFixed(2) }}</td>
          <td>{{ (item.quantity * item.price).toFixed(2) }}</td>
        </tr>
        <tfoot>
          <tr>
            <td></td>
            <td></td>
            <td></td>
            <td></td>
            <td>
              <b>{{ orderTotal() }}</b>
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  </div>
  <div class="order-detail" v-else>
    <h3>Loading...</h3>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useProductStore, useOrderStore } from '@/stores'

const productStore = useProductStore()
const orderStore = useOrderStore()
const route = useRoute()
const router = useRouter()
const orderId = computed(() => route.params.id)

const order = computed(() => {
  return orderStore.orders.find((order) => order.orderId == orderId.value)
})

const orderExists = computed(() => !!order.value)

const orderTotal = () => {
  return order.value?.items
    .reduce((total, item) => total + item.quantity * item.price, 0)
    .toFixed(2)
}

const productLookup = (productId: string | number) => {
  return productStore.products.find((product) => product.id == productId)?.name
}

const completeOrder = () => {
  if (order.value) {
    console.log(`Completing order ${order.value?.orderId}`)

    const foundOrder = orderStore.orders.find((o) => o.orderId == order.value?.orderId)

    if (foundOrder) {
      foundOrder.status = 1
      fetch(`/api/makeline/order`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(foundOrder),
      })
        .then((response) => {
          if (response.ok) {
            orderStore.removeOrder(foundOrder)
            alert('Order successfully processed')
            router.push('/')
          } else {
            alert('Error occurred while processing order')
          }
        })
        .catch((error) => {
          console.log(error)
          alert('Error occurred while processing order')
        })
    }
  }
}
</script>

<style scoped>
a {
  color: #0000ff;
  text-decoration: underline;
}

.order-detail {
  text-align: left;
}
</style>
