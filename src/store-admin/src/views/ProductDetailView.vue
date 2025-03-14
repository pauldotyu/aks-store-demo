<template>
  <div class="action-button">
    <router-link :to="`/product/${productId}/edit`">
      <button class="button">Edit Product</button>
    </router-link>
  </div>
  <br />
  <div class="product-detail" v-if="productExists">
    <div class="product-image">
      <img :src="product?.image" alt="Product Image" />
    </div>
    <div class="product-info">
      <h2>{{ product?.name }} - {{ product?.price }}</h2>
      <small>Product ID: {{ product?.id }}</small>
      <p>{{ product?.description }}</p>
    </div>
  </div>
  <div class="product-detail" v-else>
    <h3>Product not found</h3>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useProductStore } from '@/stores'

const productStore = useProductStore()
const route = useRoute()
const productId = computed(() => route.params.id as string)

const product = computed(() => {
  return productStore.products.find((product) => product.id == productId.value)
})

const productExists = computed(() => !!product.value)
</script>

<style scoped>
a {
  color: #0000ff;
  text-decoration: underline;
}

.product-detail {
  flex: 1;
  display: flex;
}

.product-image {
  flex: 1;
  margin-right: 20px;
}

.product-image img {
  width: 100%;
  height: auto;
}

.product-info {
  flex: 1;
  text-align: left;
}

.product-info h2 {
  font-size: 24px;
  margin-bottom: 10px;
}

.product-info p {
  font-size: 16px;
  margin-bottom: 20px;
}

@media (max-width: 768px) {
  .product-detail {
    flex-direction: column;
  }
}
</style>
