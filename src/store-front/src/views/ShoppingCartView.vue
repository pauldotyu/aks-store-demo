<template>
  <div class="shopping-cart" v-if="hasCartItems">
    <table class="shopping-cart-table">
      <thead>
        <tr>
          <th>Item</th>
          <th>Quantity</th>
          <th>Price</th>
          <th>Total</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in cartItems" :key="item.product.id">
          <td>{{ item.product.name }}</td>
          <td>{{ item.quantity }}</td>
          <td>{{ item.product.price }}</td>
          <td>{{ getItemTotal(item) }}</td>
          <td><button @click="removeFromCart(item)">Remove</button></td>
        </tr>
      </tbody>
    </table>
    <button class="checkout-button" @click="submitOrder">Checkout</button>
  </div>
  <div class="shopping-cart" v-else>
    <h3>Your shopping cart is empty</h3>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useCartStore } from '@/stores'
import type { CartItem } from '@/types'

const cartStore = useCartStore()

const cartItems = computed(() => cartStore.items)
const hasCartItems = computed(() => cartItems.value.length > 0)
const getItemTotal = (item: CartItem) => (item.product.price * item.quantity).toFixed(2)

const removeFromCart = (item: CartItem) => {
  cartStore.removeItem(item.product.id)
}

const submitOrder = () => {
  const order = {
    customerId: Math.floor(Math.random() * 10000000000).toString(),
    items: cartItems.value.map((item) => ({
      productId: item.product.id,
      quantity: item.quantity,
      price: item.product.price,
    })),
  }

  fetch('/api/orders', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(order),
  })
    .then((response) => {
      if (response.ok) {
        cartStore.clear()
        alert('Order submitted successfully')
      } else {
        alert('Error occurred while submitting order')
      }
    })
    .catch((error) => {
      console.error('Error submitting order:', error)
      alert('Error occurred while submitting order')
    })
}
</script>
