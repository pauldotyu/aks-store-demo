<template>
  <div class="action-button">
    <router-link to="/product/add">
      <button class="button">Add Product</button>
    </router-link>
  </div>
  <div class="product-list">
    <table>
      <thead>
        <tr>
          <th>Product ID</th>
          <th>Product Name</th>
          <th>Product Description</th>
          <th>Price</th>
        </tr>
      </thead>
      <tr v-for="product in products" :key="product.id">
        <td>
          <router-link :to="`/product/${product.id}`">{{ product.id }}</router-link>
        </td>
        <td>{{ product.name }}</td>
        <td>{{ product.description }}</td>
        <td>{{ product.price }}</td>
      </tr>
    </table>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useProductStore } from '@/stores'

const productStore = useProductStore()

const products = computed(() => productStore.products)
</script>

<style scoped>
a {
  color: #0000ff;
  text-decoration: underline;
}

.product-list {
  text-align: left;
}
</style>
