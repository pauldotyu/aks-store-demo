'use strict'
const { randomUUID } = require('crypto')

function isPositiveInteger(value) {
  return Number.isInteger(value) && value > 0
}

function validateAndNormalizeOrder(body) {
  if (typeof body !== 'object' || body === null) {
    return { valid: false, message: 'Request body must be a JSON object' }
  }

  if (typeof body.customerId !== 'string' || body.customerId.trim().length === 0) {
    return { valid: false, message: 'customerId is required and must be a non-empty string' }
  }

  if (!Array.isArray(body.items) || body.items.length === 0) {
    return { valid: false, message: 'items is required and must be a non-empty array' }
  }

  const normalizedItems = []
  for (let i = 0; i < body.items.length; i++) {
    const item = body.items[i]
    if (typeof item !== 'object' || item === null) {
      return { valid: false, message: `items[${i}] must be an object` }
    }
    if (!isPositiveInteger(item.productId)) {
      return { valid: false, message: `items[${i}].productId must be a positive integer` }
    }
    if (!isPositiveInteger(item.quantity)) {
      return { valid: false, message: `items[${i}].quantity must be a positive integer` }
    }
    if (typeof item.price !== 'number' || Number.isNaN(item.price) || item.price < 0) {
      return { valid: false, message: `items[${i}].price must be a non-negative number` }
    }

    normalizedItems.push({
      productId: item.productId,
      quantity: item.quantity,
      price: item.price
    })
  }

  return {
    valid: true,
    order: {
      customerId: body.customerId.trim(),
      items: normalizedItems
    }
  }
}

module.exports = async function (fastify, opts) {
  fastify.post('/', async function (request, reply) {
    const validation = validateAndNormalizeOrder(request.body)
    if (!validation.valid) {
      return reply.code(400).send({ error: validation.message })
    }

    const correlationId = request.headers['x-correlation-id'] || randomUUID()
    const orderEvent = {
      eventId: randomUUID(),
      correlationId,
      eventType: 'order.created',
      eventVersion: '1.0',
      createdAt: new Date().toISOString(),
      orderId: randomUUID(),
      customerId: validation.order.customerId,
      items: validation.order.items
    }

    const payload = Buffer.from(JSON.stringify(orderEvent))
    await fastify.sendMessage(payload)

    // Keep customer acceptance tied to the core order queue only.
    try {
      await fastify.sendAgentMessage(payload)
    } catch (err) {
      request.log.error({ err, orderId: orderEvent.orderId, correlationId }, 'failed to publish to agent order queue')
    }

    return reply.code(201).send({
      orderId: orderEvent.orderId,
      correlationId,
      eventId: orderEvent.eventId
    })
  })

  fastify.get('/health', async function (request, reply) {
    const appVersion = process.env.APP_VERSION || '0.1.0'
    return { status: 'ok', version: appVersion }
  })

  fastify.get('/hugs', async function (request, reply) {
    return { hugs: fastify.someSupport() }
  })
}
