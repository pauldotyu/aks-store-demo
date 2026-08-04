'use strict'

const fp = require('fastify-plugin')
const rabbit = require('rabbitmq-amqp-js-client')
const rhea = require('rhea')

let rabbitEnvironment = null
let rabbitConnection = null
let rabbitConnectPromise = null
const rabbitPublishers = new Map()
const initPromises = new Map()

async function ensureRabbitConnection() {
  if (rabbitConnection) return rabbitConnection
  if (rabbitConnectPromise) return rabbitConnectPromise

  rabbitConnectPromise = (async () => {
    const host = process.env.ORDER_QUEUE_HOSTNAME
    const port = parseInt(process.env.ORDER_QUEUE_PORT, 10) || 5672

    const env = rabbit.createEnvironment({
      host,
      port,
      username: process.env.ORDER_QUEUE_USERNAME,
      password: process.env.ORDER_QUEUE_PASSWORD,
    })

    try {
      const conn = await env.createConnection()
      rabbitEnvironment = env
      rabbitConnection = conn
      return conn
    } catch (err) {
      await env.close().catch(() => {})
      throw err
    } finally {
      rabbitConnectPromise = null
    }
  })()

  return rabbitConnectPromise
}

async function ensureRabbitPublisher(queueName) {
  if (rabbitPublishers.has(queueName)) return rabbitPublishers.get(queueName)

  // Coalesce concurrent calls into a single init attempt
  if (initPromises.has(queueName)) return initPromises.get(queueName)

  const initPromise = (async () => {
    try {
      const conn = await ensureRabbitConnection()

      const management = conn.management()
      await management.declareQueue(queueName, { type: 'classic' })
      management.close()

      const publisher = await conn.createPublisher({
        queue: { name: queueName },
      })

      rabbitPublishers.set(queueName, publisher)
      return publisher
    } catch (err) {
      throw err
    } finally {
      initPromises.delete(queueName)
    }
  })()

  initPromises.set(queueName, initPromise)
  return initPromise
}

async function publishQueueMessage(message, queueName) {
  const body = message.toString()
  const hostname = process.env.ORDER_QUEUE_HOSTNAME || ''
  const isServiceBus = hostname.endsWith('.servicebus.windows.net')

  if (process.env.ORDER_QUEUE_USERNAME && process.env.ORDER_QUEUE_PASSWORD && !isServiceBus) {
    console.log(`sending message ${body} to ${queueName} on ${hostname} using local auth credentials`)

    const publisher = await ensureRabbitPublisher(queueName)
    const dataBody = rhea.message.data_section(Buffer.from(body, 'utf8'))
    const publishResult = await publisher.publish(
      rabbit.createAmqpMessage({ body: dataBody })
    )
    if (publishResult.outcome !== rabbit.OutcomeState.ACCEPTED) {
      throw new Error(`message not accepted by RabbitMQ, outcome: ${publishResult.outcome}`)
    }
    console.log(`message accepted by RabbitMQ for queue "${queueName}"`)
    return
  }

  if (isServiceBus || process.env.USE_WORKLOAD_IDENTITY_AUTH === 'true') {
    const { ServiceBusClient } = require('@azure/service-bus')
    const fullyQualifiedNamespace = hostname || process.env.AZURE_SERVICEBUS_FULLYQUALIFIEDNAMESPACE

    if (!fullyQualifiedNamespace) {
      throw new Error('no hostname set for message queue')
    }

    let credential
    if (process.env.ORDER_QUEUE_USERNAME && process.env.ORDER_QUEUE_PASSWORD) {
      const { AzureNamedKeyCredential } = require('@azure/core-auth')
      credential = new AzureNamedKeyCredential(process.env.ORDER_QUEUE_USERNAME, process.env.ORDER_QUEUE_PASSWORD)
      console.log(`sending message ${body} to ${queueName} on ${fullyQualifiedNamespace} using SAS key credentials`)
    } else {
      const { DefaultAzureCredential } = require('@azure/identity')
      credential = new DefaultAzureCredential()
      console.log(`sending message ${body} to ${queueName} on ${fullyQualifiedNamespace} using Microsoft Entra ID Workload Identity credentials`)
    }

    const sbClient = new ServiceBusClient(fullyQualifiedNamespace, credential)
    const sender = sbClient.createSender(queueName)
    try {
      await sender.sendMessages({ body: body })
    } finally {
      await sender.close()
      await sbClient.close()
    }
    return
  }

  throw new Error('no credentials set for message queue')
}

module.exports = fp(async function (fastify, opts) {
  // Initialize RabbitMQ connection and queue on startup (skip for Azure Service Bus)
  const hostname = process.env.ORDER_QUEUE_HOSTNAME || ''
  const isServiceBus = hostname.endsWith('.servicebus.windows.net')
  if (process.env.ORDER_QUEUE_USERNAME && process.env.ORDER_QUEUE_PASSWORD && !isServiceBus) {
    try {
      await ensureRabbitPublisher(process.env.ORDER_QUEUE_NAME)
      if (process.env.AGENT_ORDER_QUEUE_NAME) {
        await ensureRabbitPublisher(process.env.AGENT_ORDER_QUEUE_NAME)
      }
      console.log(`connected to RabbitMQ at ${hostname}:${process.env.ORDER_QUEUE_PORT}, queue "${process.env.ORDER_QUEUE_NAME}" declared`)
    } catch (err) {
      console.error('failed to initialize RabbitMQ connection:', err.message)
    }
  }

  fastify.addHook('onClose', async () => {
    for (const publisher of rabbitPublishers.values()) {
      publisher.close()
    }
    rabbitPublishers.clear()
    if (rabbitConnection) {
      await rabbitConnection.close()
      rabbitConnection = null
    }
    if (rabbitEnvironment) {
      await rabbitEnvironment.close()
      rabbitEnvironment = null
    }
  })

  fastify.decorate('sendMessage', async function (message) {
    await publishQueueMessage(message, process.env.ORDER_QUEUE_NAME)
  })

  fastify.decorate('sendAgentMessage', async function (message) {
    const queueName = process.env.AGENT_ORDER_QUEUE_NAME
    if (!queueName) {
      return
    }
    await publishQueueMessage(message, queueName)
  })
})
