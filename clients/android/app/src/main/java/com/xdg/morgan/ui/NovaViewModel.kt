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
import com.xdg.morgan.api.AgendaEntry
import com.xdg.morgan.api.AgendaResponse
import com.xdg.morgan.api.JournalEntry
import com.xdg.morgan.api.MeResponse
import com.xdg.morgan.api.MorganApi
import com.xdg.morgan.api.SearchResponse
import com.xdg.morgan.data.Server
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class NovaUi(
    val agenda: AgendaResponse = AgendaResponse(),
    val agendaLoaded: Boolean = false,
    val journal: List<JournalEntry> = emptyList(),
    val journalLoaded: Boolean = false,
    val me: MeResponse? = null,
    val search: SearchResponse? = null,
    val searching: Boolean = false,
    val error: String = ""
)

class NovaViewModel(val server: Server) : ViewModel() {
    private val api = MorganApi(server.url, server.token)
    private val mutableState = MutableStateFlow(NovaUi())
    private var searchJob: Job? = null

    val state: StateFlow<NovaUi> = mutableState

    private fun load(block: suspend () -> Unit) {
        viewModelScope.launch {
            try {
                block()
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                mutableState.update { it.copy(error = error.message ?: error.javaClass.simpleName) }
            }
        }
    }

    fun refreshAgenda() = load {
        val agenda = api.agenda()
        mutableState.update { it.copy(agenda = agenda, agendaLoaded = true, error = "") }
    }

    fun refreshJournal() = load {
        val journal = api.journal().entries.sortedByDescending { it.day }
        mutableState.update { it.copy(journal = journal, journalLoaded = true, error = "") }
    }

    fun refreshMe() = load {
        val me = api.me()
        mutableState.update { it.copy(me = me, error = "") }
    }

    fun toggle(entry: AgendaEntry) = load {
        api.completeReminder(entry.id, !entry.completed)
        refreshAgenda()
    }

    fun search(query: String) {
        searchJob?.cancel()
        val text = query.trim()
        if (text.isEmpty()) {
            mutableState.update { it.copy(search = null, searching = false) }
            return
        }
        searchJob = viewModelScope.launch {
            mutableState.update { it.copy(searching = true) }
            try {
                val result = api.search(text)
                mutableState.update { it.copy(search = result, searching = false, error = "") }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                mutableState.update {
                    it.copy(searching = false, error = error.message ?: error.javaClass.simpleName)
                }
            }
        }
    }
}
