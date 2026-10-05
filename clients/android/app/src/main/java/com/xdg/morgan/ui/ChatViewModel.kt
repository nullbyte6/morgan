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
package com.xdg.morgan.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.xdg.morgan.api.ApiException
import com.xdg.morgan.api.MorganApi
import com.xdg.morgan.api.StreamEvent
import com.xdg.morgan.data.Server
import com.xdg.morgan.data.VoiceRecorder
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.takeWhile
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

data class ChatMessage(val role: String, val text: String)

data class ChatUi(
    val messages: List<ChatMessage> = emptyList(),
    val busy: Boolean = false,
    val connected: Boolean = false,
    val status: String = "",
    val confirmation: StreamEvent.Confirmation? = null,
    val listening: Boolean = false,
    val level: Float = 0f,
    val transcribing: Boolean = false
)

private const val FIRST_RETRY_MILLIS = 1_000L
private const val LAST_RETRY_MILLIS = 15_000L
private const val NOT_FOUND = 404

class ChatViewModel(private val server: Server) : ViewModel() {
    private val api = MorganApi(server.url, server.token)
    private val mutableState = MutableStateFlow(ChatUi())
    private var sessionId: String? = null
    private var recorder: VoiceRecorder? = null

    val state: StateFlow<ChatUi> = mutableState

    init {
        viewModelScope.launch { connectForever() }
    }

    private suspend fun connectForever() {
        var retry = FIRST_RETRY_MILLIS
        while (viewModelScope.isActive) {
            try {
                val id = ensureSession()
                api.stream(id).takeWhile { it !is StreamEvent.Resync }.collect {
                    retry = FIRST_RETRY_MILLIS
                    handle(it)
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                if (error is ApiException && error.status == NOT_FOUND) sessionId = null
                mutableState.update {
                    it.copy(connected = false, status = error.message ?: error.javaClass.simpleName)
                }
            }
            mutableState.update { it.copy(connected = false) }
            delay(retry)
            retry = (retry * 2).coerceAtMost(LAST_RETRY_MILLIS)
        }
    }

    private suspend fun ensureSession(): String {
        sessionId?.let { known ->
            try {
                api.session(known)
                return known
            } catch (error: ApiException) {
                if (error.status != NOT_FOUND) throw error
            }
        }
        val id = api.sessions().firstOrNull()?.id ?: api.createSession().id
        sessionId = id
        return id
    }

    private fun handle(event: StreamEvent) {
        when (event) {
            is StreamEvent.Snapshot -> mutableState.update {
                val history = event.transcript.map { entry -> ChatMessage(entry.role, entry.text) }
                val partial = if (event.partial.isEmpty()) {
                    emptyList()
                } else {
                    listOf(ChatMessage("assistant", event.partial))
                }
                it.copy(
                    messages = history + partial,
                    busy = event.busy,
                    connected = true,
                    status = "",
                    confirmation = event.confirmation
                )
            }
            is StreamEvent.Chunk -> mutableState.update { it.copy(messages = appendChunk(it.messages, event.text)) }
            is StreamEvent.Step -> mutableState.update {
                it.copy(status = listOf(event.tool, event.subject).filter(String::isNotEmpty).joinToString(" · "))
            }
            is StreamEvent.Finished -> mutableState.update {
                it.copy(messages = finishReply(it.messages, event.reply), busy = false, status = "")
            }
            is StreamEvent.Failed -> mutableState.update {
                it.copy(
                    messages = dropEmptyReply(it.messages) + ChatMessage("system", event.error),
                    busy = false,
                    status = ""
                )
            }
            is StreamEvent.Confirmation -> mutableState.update { it.copy(confirmation = event) }
            is StreamEvent.ConfirmationClosed -> mutableState.update {
                if (it.confirmation?.id == event.id) it.copy(confirmation = null) else it
            }
            is StreamEvent.ConfirmationBlocked -> mutableState.update {
                it.copy(messages = it.messages + ChatMessage("system", event.message))
            }
            is StreamEvent.Closed -> sessionId = null
            is StreamEvent.Ready, is StreamEvent.Resync, is StreamEvent.Ignored -> Unit
        }
    }

    private fun appendChunk(messages: List<ChatMessage>, text: String): List<ChatMessage> {
        val last = messages.lastOrNull()
        return if (last != null && last.role == "assistant") {
            messages.dropLast(1) + last.copy(text = last.text + text)
        } else {
            messages + ChatMessage("assistant", text)
        }
    }

    private fun finishReply(messages: List<ChatMessage>, reply: String): List<ChatMessage> {
        val last = messages.lastOrNull()
        val base = if (last != null && last.role == "assistant") messages.dropLast(1) else messages
        return if (reply.isEmpty()) base else base + ChatMessage("assistant", reply)
    }

    private fun dropEmptyReply(messages: List<ChatMessage>): List<ChatMessage> {
        val last = messages.lastOrNull()
        return if (last != null && last.role == "assistant" && last.text.isEmpty()) messages.dropLast(1) else messages
    }

    fun send(text: String) {
        val id = sessionId
        val message = text.trim()
        if (message.isEmpty() || mutableState.value.busy) return
        if (id == null || !mutableState.value.connected) {
            mutableState.update { it.copy(status = "Not connected") }
            return
        }
        mutableState.update {
            it.copy(messages = it.messages + ChatMessage("user", message), busy = true, status = "")
        }
        viewModelScope.launch {
            try {
                api.sendMessage(id, message)
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                mutableState.update {
                    it.copy(
                        messages = it.messages + ChatMessage("system", error.message ?: error.javaClass.simpleName),
                        busy = false
                    )
                }
            }
        }
    }

    fun startListening() {
        val current = mutableState.value
        if (recorder != null || current.busy || current.transcribing || !current.connected) return
        val next = VoiceRecorder { level -> mutableState.update { it.copy(level = level) } }
        try {
            next.start()
        } catch (error: Exception) {
            mutableState.update { it.copy(status = error.message ?: "The microphone is not available") }
            return
        }
        recorder = next
        mutableState.update { it.copy(listening = true, level = 0f, status = "") }
    }

    fun stopListening() {
        val active = recorder ?: return
        recorder = null
        mutableState.update { it.copy(listening = false, level = 0f, transcribing = true, status = "Transcribing…") }
        viewModelScope.launch {
            try {
                val clip = withContext(Dispatchers.Default) { active.stop() }
                if (clip.isEmpty()) {
                    mutableState.update { it.copy(transcribing = false, status = "Too short") }
                    return@launch
                }
                val text = api.transcribe(clip)
                mutableState.update { it.copy(transcribing = false, status = if (text.isBlank()) "Didn't catch that" else "") }
                if (text.isNotBlank()) send(text)
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                mutableState.update {
                    it.copy(
                        transcribing = false,
                        status = "",
                        messages = it.messages + ChatMessage("system", error.message ?: error.javaClass.simpleName)
                    )
                }
            }
        }
    }

    fun cancelListening() {
        recorder?.cancel()
        recorder = null
        mutableState.update { it.copy(listening = false, level = 0f) }
    }

    override fun onCleared() {
        recorder?.cancel()
        recorder = null
    }

    fun interrupt() {
        val id = sessionId ?: return
        viewModelScope.launch { runCatching { api.interrupt(id) } }
    }

    fun confirm(accepted: Boolean) {
        val id = sessionId ?: return
        val pending = mutableState.value.confirmation ?: return
        mutableState.update { it.copy(confirmation = null) }
        viewModelScope.launch { runCatching { api.confirm(id, pending.id, accepted) } }
    }
}
