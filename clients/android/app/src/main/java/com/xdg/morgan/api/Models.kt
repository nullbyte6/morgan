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

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class PairRequest(
    val code: String,
    @SerialName("device_name") val deviceName: String
)

@Serializable
data class PairResponse(
    @SerialName("device_id") val deviceId: String,
    val token: String
)

@Serializable
data class MeResponse(
    val assistant: String,
    val version: String,
    val language: String = "",
    @SerialName("remote_confirmation") val remoteConfirmation: Boolean = false
)

@Serializable
data class SessionSummary(
    val id: String,
    val ready: Boolean = false,
    val busy: Boolean = false,
    val error: String = ""
)

@Serializable
data class SessionList(val sessions: List<SessionSummary> = emptyList())

@Serializable
data class TranscriptEntry(
    val role: String,
    val text: String,
    val turn: Int = 0
)

@Serializable
data class SessionDetail(
    val id: String,
    val ready: Boolean = false,
    val busy: Boolean = false,
    val error: String = "",
    val transcript: List<TranscriptEntry> = emptyList()
)

@Serializable
data class MessageRequest(val text: String)

@Serializable
data class TurnResponse(val turn: Int)

@Serializable
data class ConfirmationRequest(val accepted: Boolean)

@Serializable
data class AgendaEntry(
    val id: String,
    val kind: String,
    val title: String,
    val notes: String? = null,
    @SerialName("remind_at") val remindAt: String? = null,
    val completed: Boolean = false,
    @SerialName("starts_at") val startsAt: String? = null,
    @SerialName("ends_at") val endsAt: String? = null,
    @SerialName("all_day") val allDay: Boolean = false,
    val repeat: String? = null,
    val flag: String? = null
)

@Serializable
data class AgendaResponse(
    val overdue: List<AgendaEntry> = emptyList(),
    val entries: List<AgendaEntry> = emptyList()
)

@Serializable
data class JournalEntry(
    val id: String,
    val day: String,
    val text: String,
    @SerialName("written_by") val writtenBy: String = "user"
)

@Serializable
data class JournalResponse(val entries: List<JournalEntry> = emptyList())

@Serializable
data class SearchResponse(
    val agenda: List<AgendaEntry> = emptyList(),
    val journal: List<JournalEntry> = emptyList()
)

@Serializable
data class CompletionRequest(val completed: Boolean)
