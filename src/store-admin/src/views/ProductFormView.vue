<template>
  <div class="action-button">
    <button @click="saveProduct" class="button">Save Product</button>
  </div>
  <br />
  <div v-if="showValidationErrors" class="error">
    <br />
    <ul v-for="error in validationErrors" :key="error">
      <li>{{ error }}</li>
    </ul>
  </div>
  <div class="product-form">
    <table>
      <tbody>
        <tr>
          <td><label for="product-name">Name</label></td>
          <td><input id="product-name" placeholder="Product Name" v-model="product.name" /></td>
          <td></td>
        </tr>

        <tr>
          <td><label for="product-price">Price</label></td>
          <td>
            <input
              id="product-price"
              placeholder="Product Price"
              v-model="product.price"
              type="number"
              step="0.01"
            />
          </td>
          <td></td>
        </tr>

        <tr>
          <td><label for="product-tags">Keywords</label></td>
          <td><input id="product-tags" placeholder="Product Keywords" v-model="product.tags" /></td>
          <td></td>
        </tr>

        <tr>
          <td><label for="product-description">Description</label></td>
          <td>
            <textarea
              rows="8"
              id="product-description"
              placeholder="Product Description"
              v-model="product.description"
            />
            <input type="hidden" id="product-id" placeholder="Product ID" v-model="product.id" />
          </td>
          <td>
            <button
              @click="generateDescription"
              class="ai-button"
              v-show="aiCapabilities.includes('description')"
            >
              Ask AI Assistant
            </button>
          </td>
        </tr>

        <tr>
          <td><label for="product-image">Image</label></td>
          <td>
            <input
              id="product-image-text"
              placeholder="Product Image"
              v-model="product.image"
              v-show="!aiCapabilities.includes('image')"
            />
            <div
              id="product-image-container"
              class="image-container"
              :class="{ loading: isLoadingImage }"
              style="display: flex; align-items: center"
              v-show="aiCapabilities.includes('image')"
            >
              <img v-if="product.image" :src="product.image" alt="Product Image" />
              <div class="overlay">{{ overlayText }}</div>
            </div>
          </td>
          <td>
            <button
              id="product-image-btn"
              @click="generateImage"
              class="ai-button"
              v-show="aiCapabilities.includes('image')"
            >
              Generate Image
            </button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useProductStore } from '@/stores'
import type { Product } from '@/types'

const aiServiceUrl = '/api/ai'
const productServiceUrl = '/api/product'

const productStore = useProductStore()
const route = useRoute()
const router = useRouter()

const DEFAULT_PRODUCT: Product = {
  id: 0,
  name: '',
  price: 0,
  tags: '',
  description: '',
  image: '/placeholder.png',
}

const product = ref<Product>({ ...DEFAULT_PRODUCT })

const aiCapabilities = ref<string[]>([])
const showValidationErrors = ref(false)
const isLoadingImage = ref(false)
const overlayText = ref('')

const validationErrors = computed(() => {
  const errors: string[] = []
  if (product.value.name.length === 0) {
    errors.push('Please enter a value for the name field')
  }

  if (!product.value.description || product.value.description.length === 0) {
    errors.push('Please enter a value for the description field')
  }

  if (product.value.price <= 0) {
    errors.push('Please enter a value greater than 0 for the price field')
  }

  return errors
})

const generateDescription = (): void => {
  // ensure the tag has a value
  if (
    !product.value.tags ||
    (Array.isArray(product.value.tags) && product.value.tags.length === 0) ||
    (typeof product.value.tags === 'string' && product.value.tags === '')
  ) {
    alert('Please enter a value for the keywords field')
    return
  }

  const intervalId = waitForAI()

  const tags =
    typeof product.value.tags === 'string'
      ? product.value.tags.split(',').map((tag) => tag.trim())
      : product.value.tags

  const requestBody = {
    name: product.value.name,
    tags,
  }

  product.value.description = ''

  fetch(`${aiServiceUrl}/generate/description`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(requestBody),
  })
    .then((response) => response.json())
    .then((productResponse) => {
      product.value.description = productResponse.description
    })
    .catch((error) => {
      console.log(error)
      alert('Error occurred while generating product description')
    })
    .finally(() => {
      clearInterval(intervalId)
    })
}

const generateImage = (): void => {
  // ensure the tag has a value
  if (!product.value.description || product.value.description === '') {
    alert('Please enter a product description')
    return
  }

  isLoadingImage.value = true
  overlayText.value = 'Drawing...'

  const requestBody = {
    name: product.value.name,
    description: product.value.description,
  }

  fetch(`${aiServiceUrl}/generate/image`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(requestBody),
  })
    .then((response) => {
      return response.json()
    })
    .then((productResponse) => {
      overlayText.value = 'Downloading...'
      product.value.image = ''
      product.value.image = productResponse.image
    })
    .catch((error) => {
      console.log(error)
      alert('Error occurred while generating product image')
    })
    .finally(() => {
      isLoadingImage.value = false
    })
}

const waitForAI = (): ReturnType<typeof setInterval> => {
  let dots = ''
  const intervalId = setInterval(() => {
    dots += '.'
    product.value.description = `Thinking${dots}`
  }, 500)
  return intervalId
}

const saveProduct = (): void => {
  if (validationErrors.value.length > 0) {
    showValidationErrors.value = true
    return
  }

  // default to updates
  let method = 'PUT'

  // get the path of the current request
  const path = route.path
  if (path.includes('add')) {
    method = 'POST'
  }

  // upsert the product
  fetch(`${productServiceUrl}`, {
    method: method,
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(product.value),
  })
    .then((response) => response.json())
    .then((data) => {
      alert('Product saved successfully')
      // update or add the product to the list
      if (method === 'PUT') {
        productStore.updateProduct(data)
      } else {
        productStore.addProduct(data)
      }
      router.push(`/product/${data.id}`)
    })
    .catch((error) => {
      console.log(error)
      alert('Error occurred while saving product')
    })
}

onMounted(() => {
  if (route.params.id && route.params.id !== 'add') {
    const foundProduct = productStore.products.find((p) => p.id == route.params.id)
    if (foundProduct) {
      // Copy all properties from the found product to our local product
      Object.assign(product.value, foundProduct)
    } else {
      alert('Product not found')
    }
  }

  fetch(`${aiServiceUrl}/health`)
    .then((response) => response.json())
    .then((data) => {
      if (data.status === 'ok') {
        console.log('ai service health is ok')
        aiCapabilities.value = data.capabilities
      } else {
        console.log('ai service health is not ok')
      }
    })
    .catch((error) => {
      console.log('error occurred when evaluating ai service health')
      console.log(error)
    })
})
</script>

<style scoped>
ul {
  justify-content: center;
  list-style: none;
  margin: 0;
  padding: 0;
  width: 100%;
  color: #ff0000;
}

img {
  width: 100%;
}

table {
  border-collapse: collapse;
}

td {
  vertical-align: center;
  border: none;
}

.product-form {
  display: flex;
  justify-content: center;
}

.product-form input {
  padding: 5px;
  margin: 5px;
}

.ai-button {
  height: 60px;
}

.image-container {
  position: relative;
  width: 102%;
}

.overlay {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(0, 0, 0, 0.5);
  color: white;
  display: flex;
  justify-content: center;
  align-items: center;
  opacity: 0;
  transition: opacity 0.3s ease;
  font-size: x-large;
  font-weight: bolder;
}

.image-container.loading .overlay {
  opacity: 1;
}
</style>
