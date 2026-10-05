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

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.decodeFromJsonElement
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

sealed interface StreamEvent {
    data class Snapshot(
        val ready: Boolean,
        val busy: Boolean,
        val partial: String,
        val transcript: List<TranscriptEntry>,
        val confirmation: Confirmation?
    ) : StreamEvent

    data class Confirmation(val id: Int, val message: String, val timeoutSeconds: Int) : StreamEvent
    data class ConfirmationClosed(val id: Int) : StreamEvent
    data class ConfirmationBlocked(val message: String) : StreamEvent
    data class Chunk(val text: String) : StreamEvent
    data class Step(val tool: String, val subject: String) : StreamEvent
    data class Finished(val reply: String) : StreamEvent
    data class Failed(val error: String) : StreamEvent
    data object Ready : StreamEvent
    data object Closed : StreamEvent
    data object Resync : StreamEvent
    data object Ignored : StreamEvent
}

private val eventJson = Json { ignoreUnknownKeys = true }

private fun JsonObject.text(key: String): String = this[key]?.jsonPrimitive?.contentOrNull.orEmpty()

private fun JsonObject.number(key: String, fallback: Int = 0): Int =
    this[key]?.jsonPrimitive?.intOrNull ?: fallback

private fun JsonObject.confirmation() = StreamEvent.Confirmation(
    id = number("id"),
    message = text("message"),
    timeoutSeconds = number("timeout", 30)
)

fun parseEvent(frame: String): StreamEvent {
    val event = eventJson.parseToJsonElement(frame).jsonObject
    return when (event.text("type")) {
        "snapshot" -> {
            val session = event["session"] as? JsonObject
            StreamEvent.Snapshot(
                ready = session?.get("ready")?.jsonPrimitive?.booleanOrNull ?: false,
                busy = session?.get("busy")?.jsonPrimitive?.booleanOrNull ?: false,
                partial = event.text("partial"),
                transcript = event["transcript"]?.let {
                    eventJson.decodeFromJsonElement<List<TranscriptEntry>>(it)
                }.orEmpty(),
                confirmation = (event["confirmation"] as? JsonObject)?.confirmation()
            )
        }
        "confirmation" -> event.confirmation()
        "confirmation_closed" -> StreamEvent.ConfirmationClosed(event.number("id"))
        "confirmation_blocked" -> StreamEvent.ConfirmationBlocked(event.text("message"))
        "chunk" -> StreamEvent.Chunk(event.text("text"))
        "step" -> StreamEvent.Step(event.text("tool"), event.text("subject"))
        "finished" -> StreamEvent.Finished(event.text("reply"))
        "failed", "rejected" -> StreamEvent.Failed(event.text("error"))
        "ready" -> StreamEvent.Ready
        "closed" -> StreamEvent.Closed
        "resync" -> StreamEvent.Resync
        else -> StreamEvent.Ignored
    }
}
