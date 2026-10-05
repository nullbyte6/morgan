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
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.takeWhile
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class ChatUi(
    val reply: String = "",
    val error: String = "",
    val busy: Boolean = false,
    val connected: Boolean = false,
    val status: String = "",
    val confirmation: StreamEvent.Confirmation? = null,
    val orb: OrbState = OrbState.Idle,
    val listening: Boolean = false,
    val transcribing: Boolean = false,
    val levels: List<Float> = emptyList()
)

private const val FIRST_RETRY_MILLIS = 1_000L
private const val LAST_RETRY_MILLIS = 15_000L
private const val SUCCESS_MILLIS = 1_400L
private const val ERROR_MILLIS = 2_500L
private const val NOT_FOUND = 404

class ChatViewModel(private val server: Server) : ViewModel() {
    private val api = MorganApi(server.url, server.token)
    private val mutableState = MutableStateFlow(ChatUi())
    private var sessionId: String? = null
    private var recorder: VoiceRecorder? = null
    private var settleJob: Job? = null
    private var lifecycle = "idle"
    private var executing = false
    private var writing = false
    private var denied = false
    private var waiting = false
    private var settled = true

    val state: StateFlow<ChatUi> = mutableState

    init {
        viewModelScope.launch { connectForever() }
    }

    private fun orbFor(ui: ChatUi): OrbState = when {
        ui.transcribing -> OrbState.Processing
        settled -> OrbState.Idle
        waiting -> OrbState.AwaitingPermission
        denied || lifecycle == "blocked" || lifecycle == "failed" -> OrbState.DeniedError
        lifecycle in IDLE_LIFECYCLES -> OrbState.Idle
        lifecycle == "complete" -> OrbState.Success
        executing -> OrbState.Executing
        writing -> OrbState.Writing
        else -> OrbState.Processing
    }

    private fun change(block: (ChatUi) -> ChatUi) {
        mutableState.update { block(it).let { next -> next.copy(orb = orbFor(next)) } }
    }

    private fun settleAfter(millis: Long) {
        settleJob?.cancel()
        settleJob = viewModelScope.launch {
            delay(millis)
            settled = true
            change { it }
        }
    }

    private fun begin() {
        settleJob?.cancel()
        settled = false
        lifecycle = "active"
        executing = false
        writing = false
        denied = false
        waiting = false
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
                change { it.copy(connected = false, status = error.message ?: error.javaClass.simpleName) }
            }
            change { it.copy(connected = false) }
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
            is StreamEvent.Snapshot -> {
                if (event.busy) begin() else {
                    settleJob?.cancel()
                    settled = true
                    lifecycle = "idle"
                }
                writing = event.partial.isNotEmpty()
                waiting = event.confirmation != null
                change {
                    it.copy(
                        reply = event.partial,
                        error = "",
                        busy = event.busy,
                        connected = true,
                        status = "",
                        confirmation = event.confirmation
                    )
                }
            }
            is StreamEvent.Chunk -> {
                settled = false
                executing = false
                writing = true
                change { it.copy(reply = it.reply + event.text) }
            }
            is StreamEvent.Step -> change {
                it.copy(status = listOf(event.tool, event.subject).filter(String::isNotEmpty).joinToString(" · "))
            }
            is StreamEvent.Activity -> {
                if (event.lifecycle.isNotEmpty()) lifecycle = event.lifecycle
                executing = event.event == "started"
                writing = false
                change { it }
            }
            is StreamEvent.Finished -> {
                executing = false
                writing = false
                waiting = false
                if (event.reply.isEmpty() && mutableState.value.reply.isEmpty()) {
                    lifecycle = "idle"
                    settled = true
                } else {
                    lifecycle = if (denied) "failed" else "complete"
                    settled = false
                    settleAfter(if (denied) ERROR_MILLIS else SUCCESS_MILLIS)
                }
                change { it.copy(reply = event.reply.ifEmpty { it.reply }, busy = false, status = "") }
            }
            is StreamEvent.Failed -> {
                executing = false
                writing = false
                waiting = false
                lifecycle = "failed"
                settled = false
                settleAfter(ERROR_MILLIS)
                change { it.copy(error = event.error, busy = false, status = "") }
            }
            is StreamEvent.PermissionDenied -> {
                denied = true
                change { it }
            }
            is StreamEvent.Confirmation -> {
                waiting = true
                change { it.copy(confirmation = event) }
            }
            is StreamEvent.ConfirmationClosed -> {
                waiting = false
                change { if (it.confirmation?.id == event.id) it.copy(confirmation = null) else it }
            }
            is StreamEvent.ConfirmationBlocked -> {
                denied = true
                change { it.copy(error = "Needs approval on the PC: ${event.message}") }
            }
            is StreamEvent.Closed -> sessionId = null
            is StreamEvent.Ready, is StreamEvent.Resync, is StreamEvent.Ignored -> Unit
        }
    }

    fun send(text: String) {
        val id = sessionId
        val message = text.trim()
        if (message.isEmpty() || mutableState.value.busy) return
        if (id == null || !mutableState.value.connected) {
            change { it.copy(status = "Not connected") }
            return
        }
        begin()
        change { it.copy(reply = "", error = "", busy = true, status = "") }
        viewModelScope.launch {
            try {
                api.sendMessage(id, message)
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                lifecycle = "failed"
                settleAfter(ERROR_MILLIS)
                change { it.copy(error = error.message ?: error.javaClass.simpleName, busy = false) }
            }
        }
    }

    fun startListening() {
        val current = mutableState.value
        if (recorder != null || current.busy || current.transcribing || !current.connected) return
        val next = VoiceRecorder { levels -> change { it.copy(levels = levels) } }
        try {
            next.start()
        } catch (error: Exception) {
            change { it.copy(status = error.message ?: "The microphone is not available") }
            return
        }
        recorder = next
        change { it.copy(listening = true, levels = emptyList(), status = "", error = "") }
    }

    fun stopListening() {
        val active = recorder ?: return
        recorder = null
        change { it.copy(listening = false, levels = emptyList(), transcribing = true, status = "Transcribing…") }
        viewModelScope.launch {
            try {
                val clip = withContext(Dispatchers.Default) { active.stop() }
                if (clip.isEmpty()) {
                    change { it.copy(transcribing = false, status = "Too short") }
                    return@launch
                }
                val text = api.transcribe(clip)
                change { it.copy(transcribing = false, status = if (text.isBlank()) "Didn't catch that" else "") }
                if (text.isNotBlank()) send(text)
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                lifecycle = "failed"
                settled = false
                settleAfter(ERROR_MILLIS)
                change {
                    it.copy(transcribing = false, status = "", error = error.message ?: error.javaClass.simpleName)
                }
            }
        }
    }

    fun cancelListening() {
        recorder?.cancel()
        recorder = null
        change { it.copy(listening = false, levels = emptyList()) }
    }

    override fun onCleared() {
        recorder?.cancel()
        recorder = null
    }

    fun interrupt() {
        val id = sessionId ?: return
        lifecycle = "cancelled"
        change { it }
        viewModelScope.launch { runCatching { api.interrupt(id) } }
    }

    fun confirm(accepted: Boolean) {
        val id = sessionId ?: return
        val pending = mutableState.value.confirmation ?: return
        waiting = false
        change { it.copy(confirmation = null) }
        viewModelScope.launch { runCatching { api.confirm(id, pending.id, accepted) } }
    }

    private companion object {
        val IDLE_LIFECYCLES = setOf("interrupted", "cancelled", "limit_reached", "idle")
    }
}
