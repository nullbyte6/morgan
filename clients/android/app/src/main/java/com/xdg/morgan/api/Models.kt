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
