/**
 * RalseiBot Dashboard - Interactive Client-side Script
 */

document.addEventListener('DOMContentLoaded', () => {
  initToasts();
  initServerSearch();
  initTabs();
  initCommandFilters();
  initCategoryToggles();
  initFormSaves();
});

// ==========================================================================
// TOAST NOTIFICATIONS
// ==========================================================================
function showToast(message, type = 'info', duration = 4000) {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;

  let icon = 'fa-circle-info';
  if (type === 'success') icon = 'fa-circle-check';
  if (type === 'error') icon = 'fa-circle-exclamation';

  toast.innerHTML = `
    <i class="fa-solid ${icon}"></i>
    <span>${message}</span>
  `;

  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px) scale(0.95)';
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

function setSaveIndicator(status) {
  const indicator = document.getElementById('save-status-indicator');
  if (!indicator) return;

  if (status === 'saving') {
    indicator.className = 'save-indicator saving';
    indicator.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> <span>Salvando...</span>';
  } else if (status === 'synced') {
    indicator.className = 'save-indicator synced';
    indicator.innerHTML = '<i class="fa-solid fa-circle-check"></i> <span>Tudo salvo</span>';
  } else if (status === 'error') {
    indicator.className = 'save-indicator error';
    indicator.innerHTML = '<i class="fa-solid fa-circle-exclamation"></i> <span>Erro ao salvar</span>';
  }
}

// ==========================================================================
// SERVER LIST FILTER & SEARCH
// ==========================================================================
function initServerSearch() {
  const searchInput = document.getElementById('server-search');
  const clearBtn = document.getElementById('clear-search');
  const filterTabs = document.querySelectorAll('.filter-tab');
  const cards = document.querySelectorAll('.guild-card');
  const noResults = document.getElementById('no-search-results');

  if (!searchInput && filterTabs.length === 0) return;

  let currentFilter = 'all';

  function applyFilters() {
    const query = searchInput ? searchInput.value.trim().toLowerCase() : '';
    let visibleCount = 0;

    cards.forEach(card => {
      const name = card.getAttribute('data-name') || '';
      const hasBot = card.getAttribute('data-has-bot') === 'true';

      const matchesSearch = query === '' || name.includes(query);
      let matchesFilter = true;

      if (currentFilter === 'active') matchesFilter = hasBot;
      if (currentFilter === 'missing') matchesFilter = !hasBot;

      if (matchesSearch && matchesFilter) {
        card.style.display = 'flex';
        visibleCount++;
      } else {
        card.style.display = 'none';
      }
    });

    if (clearBtn) {
      clearBtn.style.display = query ? 'block' : 'none';
    }

    if (noResults) {
      noResults.style.display = visibleCount === 0 ? 'block' : 'none';
    }
  }

  if (searchInput) {
    searchInput.addEventListener('input', applyFilters);
  }

  if (clearBtn) {
    clearBtn.addEventListener('click', () => {
      searchInput.value = '';
      applyFilters();
      searchInput.focus();
    });
  }

  filterTabs.forEach(tab => {
    tab.addEventListener('click', () => {
      filterTabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      currentFilter = tab.getAttribute('data-filter') || 'all';
      applyFilters();
    });
  });
}

// ==========================================================================
// CONFIGURATION TABS NAVIGATION
// ==========================================================================
function initTabs() {
  const tabButtons = document.querySelectorAll('.tab-btn');
  const tabPanes = document.querySelectorAll('.tab-pane');

  if (tabButtons.length === 0) return;

  tabButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      const targetId = btn.getAttribute('data-tab');

      tabButtons.forEach(b => b.classList.remove('active'));
      tabPanes.forEach(p => p.classList.remove('active'));

      btn.classList.add('active');
      const targetPane = document.getElementById(targetId);
      if (targetPane) targetPane.classList.add('active');

      // Update URL hash without scroll
      history.replaceState(null, null, `#${targetId}`);
    });
  });

  // Activate tab from URL hash if present
  if (window.location.hash) {
    const activeBtn = document.querySelector(`.tab-btn[data-tab="${window.location.hash.substring(1)}"]`);
    if (activeBtn) activeBtn.click();
  }
}

// ==========================================================================
// COMMANDS SEARCH & CATEGORY FILTER
// ==========================================================================
function initCommandFilters() {
  const searchInput = document.getElementById('command-search');
  const clearBtn = document.getElementById('clear-cmd-search');
  const filterPills = document.querySelectorAll('.cmd-filter-pill');
  const blocks = document.querySelectorAll('.category-block');
  const cards = document.querySelectorAll('.command-card');

  if (!searchInput && filterPills.length === 0) return;

  let currentCategory = 'all';

  function filterCommands() {
    const query = searchInput ? searchInput.value.trim().toLowerCase() : '';

    blocks.forEach(block => {
      const catId = block.getAttribute('data-cat-id');
      const matchesCategory = (currentCategory === 'all' || currentCategory === catId);

      let visibleInBlock = 0;
      const blockCards = block.querySelectorAll('.command-card');

      blockCards.forEach(card => {
        const cmdName = card.getAttribute('data-cmd-name') || '';
        const desc = card.querySelector('.cmd-desc')?.textContent.toLowerCase() || '';
        const matchesQuery = query === '' || cmdName.includes(query) || desc.includes(query);

        if (matchesCategory && matchesQuery) {
          card.style.display = 'flex';
          visibleInBlock++;
        } else {
          card.style.display = 'none';
        }
      });

      // Show or hide entire category block if no commands match
      block.style.display = (matchesCategory && visibleInBlock > 0) ? 'block' : 'none';
    });

    if (clearBtn) {
      clearBtn.style.display = query ? 'block' : 'none';
    }
  }

  if (searchInput) {
    searchInput.addEventListener('input', filterCommands);
  }

  if (clearBtn) {
    clearBtn.addEventListener('click', () => {
      searchInput.value = '';
      filterCommands();
      searchInput.focus();
    });
  }

  filterPills.forEach(pill => {
    pill.addEventListener('click', () => {
      filterPills.forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      currentCategory = pill.getAttribute('data-cat') || 'all';
      filterCommands();
    });
  });
}

// ==========================================================================
// COMMAND TOGGLES & MASTER CATEGORY SWITCHES
// ==========================================================================
function initCategoryToggles() {
  const masterToggles = document.querySelectorAll('.category-master-toggle');
  const cmdToggles = document.querySelectorAll('.cmd-toggle');

  function updateDisabledCount() {
    const disabledCards = document.querySelectorAll('.command-card.disabled');
    const display = document.getElementById('disabled-count-display');
    if (display) {
      const count = disabledCards.length;
      display.textContent = `${count} comando${count === 1 ? '' : 's'} desativado${count === 1 ? '' : 's'}`;
    }
  }

  masterToggles.forEach(master => {
    master.addEventListener('change', () => {
      const catKey = master.getAttribute('data-cat');
      const block = document.querySelector(`.category-block[data-cat-id="${catKey}"]`);
      if (!block) return;

      const isChecked = master.checked;
      const toggles = block.querySelectorAll('.cmd-toggle');

      toggles.forEach(toggle => {
        toggle.checked = isChecked;
        const card = toggle.closest('.command-card');
        if (card) {
          if (isChecked) {
            card.classList.remove('disabled');
          } else {
            card.classList.add('disabled');
          }
        }
      });

      updateDisabledCount();
    });
  });

  cmdToggles.forEach(toggle => {
    toggle.addEventListener('change', () => {
      const card = toggle.closest('.command-card');
      if (card) {
        if (toggle.checked) {
          card.classList.remove('disabled');
        } else {
          card.classList.add('disabled');
        }
      }

      // Check if all commands in this category are enabled
      const catKey = toggle.getAttribute('data-cat');
      const block = document.querySelector(`.category-block[data-cat-id="${catKey}"]`);
      if (block) {
        const allCatToggles = block.querySelectorAll('.cmd-toggle');
        const anyUnchecked = Array.from(allCatToggles).some(t => !t.checked);
        const master = block.querySelector('.category-master-toggle');
        if (master) master.checked = !anyUnchecked;
      }

      updateDisabledCount();
    });
  });

  updateDisabledCount();
}

// ==========================================================================
// FORM SAVES & API CALLS
// ==========================================================================
function initFormSaves() {
  const container = document.querySelector('.guild-config-container');
  if (!container) return;

  const guildId = container.getAttribute('data-guild-id');

  // 1. General & Prefix Save
  const btnSaveGeneral = document.getElementById('btn-save-general');
  if (btnSaveGeneral) {
    btnSaveGeneral.addEventListener('click', async () => {
      const prefix = document.getElementById('input-prefix')?.value.trim() || 'r.';
      const welcomeChannel = document.getElementById('select-welcome-channel')?.value || '';
      const welcomeMessage = document.getElementById('input-welcome-message')?.value || '';
      const modLogChannel = document.getElementById('select-modlog-channel')?.value || '';

      setSaveIndicator('saving');

      try {
        const res = await fetch(`/api/guild/${guildId}/settings`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            prefix: prefix,
            welcome_channel_id: welcomeChannel,
            welcome_message: welcomeMessage,
            mod_log_channel_id: modLogChannel,
          }),
        });
        const data = await res.json();
        if (res.ok && data.success) {
          setSaveIndicator('synced');
          showToast('Configurações gerais salvas com sucesso!', 'success');
        } else {
          setSaveIndicator('error');
          showToast(data.error || 'Erro ao salvar configurações.', 'error');
        }
      } catch (err) {
        setSaveIndicator('error');
        showToast('Falha na conexão com o servidor.', 'error');
      }
    });
  }

  // Reset Prefix Button
  const btnResetPrefix = document.getElementById('btn-reset-prefix');
  if (btnResetPrefix) {
    btnResetPrefix.addEventListener('click', async () => {
      const input = document.getElementById('input-prefix');
      if (input) input.value = 'r.';
      try {
        const res = await fetch(`/api/guild/${guildId}/reset-prefix`, { method: 'POST' });
        const data = await res.json();
        if (res.ok && data.success) {
          showToast("Prefixo redefinido para 'r.'", 'info');
        }
      } catch (e) {}
    });
  }

  // 2. Commands & Modules Save
  const btnSaveCommands = document.getElementById('btn-save-commands');
  if (btnSaveCommands) {
    btnSaveCommands.addEventListener('click', async () => {
      setSaveIndicator('saving');

      // Collect disabled commands and categories
      const disabledCommands = [];
      const disabledCategories = [];

      document.querySelectorAll('.category-master-toggle').forEach(master => {
        if (!master.checked) {
          disabledCategories.push(master.getAttribute('data-cat'));
        }
      });

      document.querySelectorAll('.cmd-toggle').forEach(t => {
        if (!t.checked) {
          disabledCommands.push(t.getAttribute('data-cmd'));
        }
      });

      try {
        const res = await fetch(`/api/guild/${guildId}/settings`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            disabled_commands: disabledCommands,
            disabled_categories: disabledCategories,
          }),
        });
        const data = await res.json();
        if (res.ok && data.success) {
          setSaveIndicator('synced');
          showToast('Comandos e módulos atualizados com sucesso!', 'success');
        } else {
          setSaveIndicator('error');
          showToast(data.error || 'Erro ao salvar comandos.', 'error');
        }
      } catch (err) {
        setSaveIndicator('error');
        showToast('Falha ao comunicar com o servidor.', 'error');
      }
    });
  }

  // 3. Confessions Save
  const btnSaveConfessions = document.getElementById('btn-save-confessions');
  if (btnSaveConfessions) {
    btnSaveConfessions.addEventListener('click', async () => {
      const channelId = document.getElementById('select-confession-channel')?.value || '';
      const logChannelId = document.getElementById('select-confession-log-channel')?.value || '';

      if (!channelId || !logChannelId) {
        showToast('Selecione ambos os canais de confissão e log.', 'error');
        return;
      }

      setSaveIndicator('saving');

      try {
        const res = await fetch(`/api/guild/${guildId}/confessions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            channel_id: channelId,
            log_channel_id: logChannelId,
          }),
        });
        const data = await res.json();
        if (res.ok && data.success) {
          setSaveIndicator('synced');
          showToast('Módulo de confissões configurado!', 'success');
        } else {
          setSaveIndicator('error');
          showToast(data.error || 'Erro ao configurar confissões.', 'error');
        }
      } catch (err) {
        setSaveIndicator('error');
        showToast('Erro de rede ao salvar.', 'error');
      }
    });
  }

  // 4. Tickets Save
  const btnSaveTickets = document.getElementById('btn-save-tickets');
  if (btnSaveTickets) {
    btnSaveTickets.addEventListener('click', async () => {
      const categoryId = document.getElementById('select-ticket-category')?.value || '';
      if (!categoryId) {
        showToast('Selecione a categoria para os canais de ticket.', 'error');
        return;
      }

      setSaveIndicator('saving');

      try {
        const res = await fetch(`/api/guild/${guildId}/tickets`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ category_id: categoryId }),
        });
        const data = await res.json();
        if (res.ok && data.success) {
          setSaveIndicator('synced');
          showToast('Categoria de tickets salva com sucesso!', 'success');
        } else {
          setSaveIndicator('error');
          showToast(data.error || 'Erro ao salvar categoria de tickets.', 'error');
        }
      } catch (err) {
        setSaveIndicator('error');
        showToast('Erro de rede ao salvar tickets.', 'error');
      }
    });
  }

  // 5. Quiz Save
  const quizCheck = document.getElementById('check-quiz-enabled');
  const quizFields = document.getElementById('quiz-fields');
  if (quizCheck && quizFields) {
    quizCheck.addEventListener('change', () => {
      quizFields.style.display = quizCheck.checked ? 'block' : 'none';
    });
  }

  const btnSaveQuiz = document.getElementById('btn-save-quiz');
  if (btnSaveQuiz) {
    btnSaveQuiz.addEventListener('click', async () => {
      const enabled = quizCheck ? quizCheck.checked : false;
      const channelId = document.getElementById('select-quiz-channel')?.value || '';
      const reviewChannelId = document.getElementById('select-quiz-review-channel')?.value || '';
      const reward = parseInt(document.getElementById('input-quiz-reward')?.value || '100', 10);

      if (enabled && (!channelId || !reviewChannelId)) {
        showToast('Selecione os canais do Quiz e de Revisão.', 'error');
        return;
      }

      setSaveIndicator('saving');

      try {
        const res = await fetch(`/api/guild/${guildId}/quiz`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            enabled: enabled,
            channel_id: channelId,
            review_channel_id: reviewChannelId,
            reward: reward,
          }),
        });
        const data = await res.json();
        if (res.ok && data.success) {
          setSaveIndicator('synced');
          showToast(data.message || 'Quiz configurado com sucesso!', 'success');
        } else {
          setSaveIndicator('error');
          showToast(data.error || 'Erro ao salvar configurações do Quiz.', 'error');
        }
      } catch (err) {
        setSaveIndicator('error');
        showToast('Erro de rede ao salvar quiz.', 'error');
      }
    });
  }
}

