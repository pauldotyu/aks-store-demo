<template>
  <TopNav />
  <router-view />
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useProductStore, useOrderStore } from '@/stores'
import type { Product, Order } from '@/types'
import TopNav from './components/TopNav.vue'

const productStore = useProductStore()
const orderStore = useOrderStore()

onMounted(() => {
  if (productStore.count === 0) {
    console.log('Fetching products')
    fetch('/api/products')
      .then((response) => response.json())
      .then((data: Product[]) => {
        productStore.addProducts(data)
        console.log(`Fetched ${data.length} products`)
      })
      .catch((error) => {
        console.log(error)
        alert('Error occurred while fetching products')
      })
  }
  if (orderStore.count === 0) {
    console.log('Fetching orders')
    fetch('/api/makeline/order/fetch')
      .then((response) => response.json())
      .then((data: Order[]) => {
        orderStore.addOrders(data)
        console.log(`Fetched ${data.length} orders`)
      })
      .catch((error) => {
        console.log(error)
        alert('Error occurred while fetching orders')
      })
  }
})
</script>

<style>
#app {
  font-family: Avenir, Helvetica, Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  text-align: center;
  color: #2c3e50;
  margin-top: 120px;
  padding: 1rem;
}

footer {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  background-color: #333;
  color: #fff;
  padding: 1rem;
  margin: 0;
}

nav {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

ul {
  display: flex;
  list-style: none;
  margin: 0;
  padding: 0;
}

li {
  margin: 0 1rem;
}

a {
  color: #fff;
  text-decoration: none;
}

table {
  width: 100%;
  border-collapse: collapse;
  border-spacing: 0;
}

th,
td {
  padding: 8px;
  text-align: left;
  border-bottom: 1px solid #ddd;
}

.order-detail {
  text-align: left;
}

button {
  padding: 10px;
  background-color: #005f8b;
  color: #fff;
  border: none;
  border-radius: 5px;
  cursor: pointer;
  height: 42px;
}

button:hover {
  background-color: #005f8b;
}

.action-button {
  float: right;
}

.product-detail {
  text-align: left;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  gap: 1rem;
  margin: 2rem auto;
}

.product-form {
  display: flex;
  flex-direction: column;
  align-items: left;
  justify-content: center;
  margin: 2rem auto;
  width: 50%;
}

.form-row {
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.ai-button {
  margin-left: 10px;
  padding: 10px 10px;
  border-radius: 5px;
  border: none;
  background-color: #007acc;
  color: #fff;
  cursor: pointer;
}

.ai-button:hover {
  background-color: #005f8b;
}

textarea {
  width: 100%;
  padding: 5px;
  border-radius: 5px;
  border: 1px solid #ccc;
}

label {
  text-align: right;
  margin-right: 10px;
  width: 100px;
  font-weight: bold;
}

input {
  width: 100%;
  padding: 5px;
  border-radius: 5px;
  border: 1px solid #ccc;
}
</style>
