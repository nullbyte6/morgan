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

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.xdg.morgan.api.MorganApi
import com.xdg.morgan.data.Server
import com.xdg.morgan.data.ServerStore
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

sealed interface AppState {
    data object Loading : AppState
    data object Unpaired : AppState
    data class Paired(val server: Server) : AppState
}

data class PairingUi(val busy: Boolean = false, val error: String = "")

private const val DEFAULT_PORT = 8765

class AppViewModel(application: Application) : AndroidViewModel(application) {
    private val store = ServerStore(application)

    val state: StateFlow<AppState> = store.server
        .map { if (it == null) AppState.Unpaired else AppState.Paired(it) }
        .stateIn(viewModelScope, SharingStarted.Eagerly, AppState.Loading)

    val pairing = MutableStateFlow(PairingUi())

    fun pair(url: String, code: String, deviceName: String) {
        if (pairing.value.busy) return
        pairing.value = PairingUi(busy = true)
        viewModelScope.launch {
            try {
                val base = normalize(url)
                val result = MorganApi(base).pair(code.trim(), deviceName.trim().ifEmpty { "Phone" })
                store.save(Server(base, result.token))
                pairing.value = PairingUi()
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                pairing.update { PairingUi(error = error.message ?: error.javaClass.simpleName) }
            }
        }
    }

    fun unpair(server: Server) {
        viewModelScope.launch {
            runCatching { MorganApi(server.url, server.token).unpair() }
            store.clear()
        }
    }

    private fun normalize(input: String): String {
        val trimmed = input.trim().trimEnd('/')
        val withScheme = if ("://" in trimmed) trimmed else "http://$trimmed"
        val authority = withScheme.substringAfter("://").substringBefore('/')
        return if (withScheme.startsWith("http://") && ':' !in authority) {
            withScheme.replaceFirst(authority, "$authority:$DEFAULT_PORT")
        } else {
            withScheme
        }
    }
}
