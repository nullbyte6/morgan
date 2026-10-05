/*
 *  Copyright (c) 2026 Diego.
 *
 *  SPDX-License-Identifier: GPL-3.0-or-later
 *
 *  This file is part of morgan.
 *
 *  This program is free software: you can redistribute it and/or
 *  modify it under the terms of the GNU General Public License
 *  as published by the Free Software Foundation, either version 3
 *  of the License, or (at your option) any later version.
 *
 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty
 *  of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
 *  See the GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with this program. If not, see <https://www.gnu.org/licenses/>.
 */
package com.xdg.morgan.api

import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.Call
import okhttp3.Callback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener

class ApiException(val status: Int, message: String) : Exception(message)

class MorganApi(baseUrl: String, private val token: String? = null) {
    private val base = baseUrl.trimEnd('/')
    private val json = Json { ignoreUnknownKeys = true }
    private val socketClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.SECONDS)
        .pingInterval(20, TimeUnit.SECONDS)
        .build()
    private val client = socketClient.newBuilder()
        .readTimeout(30, TimeUnit.SECONDS)
        .callTimeout(30, TimeUnit.SECONDS)
        .build()

    suspend fun pair(code: String, deviceName: String): PairResponse =
        execute(post("/v1/pair", PairRequest(code, deviceName)))

    suspend fun me(): MeResponse = execute(get("/v1/me"))

    suspend fun unpair() {
        send(request("/v1/me").delete().build())
    }

    suspend fun sessions(): List<SessionSummary> =
        execute<SessionList>(get("/v1/sessions")).sessions

    suspend fun createSession(): SessionSummary = execute(postEmpty("/v1/sessions"))

    suspend fun session(id: String): SessionDetail = execute(get("/v1/sessions/$id"))

    suspend fun sendMessage(id: String, text: String): Int =
        execute<TurnResponse>(post("/v1/sessions/$id/messages", MessageRequest(text))).turn

    suspend fun interrupt(id: String) {
        send(postEmpty("/v1/sessions/$id/interrupt"))
    }

    suspend fun confirm(id: String, requestId: Int, accepted: Boolean) {
        send(post("/v1/sessions/$id/confirmations/$requestId", ConfirmationRequest(accepted)))
    }

    fun stream(id: String): Flow<StreamEvent> = callbackFlow {
        val socket = socketClient.newWebSocket(
            request("/v1/sessions/$id/stream").build(),
            object : WebSocketListener() {
                override fun onMessage(webSocket: WebSocket, text: String) {
                    trySend(parseEvent(text))
                }

                override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                    webSocket.close(code, reason)
                }

                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                    close()
                }

                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                    close(
                        if (response != null && response.code in 400..499) {
                            ApiException(response.code, response.message)
                        } else {
                            t
                        }
                    )
                }
            }
        )
        awaitClose { socket.cancel() }
    }

    private fun request(path: String): Request.Builder =
        Request.Builder().url(base + path).apply {
            token?.let { header("Authorization", "Bearer $it") }
        }

    private fun get(path: String): Request = request(path).get().build()

    private fun postJson(path: String, payload: String): Request =
        request(path).post(payload.toRequestBody("application/json".toMediaType())).build()

    private fun postEmpty(path: String): Request = postJson(path, "{}")

    private inline fun <reified T> post(path: String, body: T): Request =
        postJson(path, json.encodeToString(body))

    private suspend inline fun <reified T> execute(request: Request): T =
        json.decodeFromString(send(request))

    private suspend fun send(request: Request): String =
        suspendCancellableCoroutine { continuation ->
            val call = client.newCall(request)
            continuation.invokeOnCancellation { call.cancel() }
            call.enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) {
                    continuation.resumeWithException(e)
                }

                override fun onResponse(call: Call, response: Response) {
                    response.use {
                        val text = it.body.string()
                        if (it.isSuccessful) {
                            continuation.resume(text)
                        } else {
                            continuation.resumeWithException(
                                ApiException(it.code, detail(text, it.message))
                            )
                        }
                    }
                }
            })
        }

    private fun detail(text: String, fallback: String): String = runCatching {
        json.parseToJsonElement(text).jsonObject["detail"]?.jsonPrimitive?.contentOrNull
    }.getOrNull() ?: fallback
}
