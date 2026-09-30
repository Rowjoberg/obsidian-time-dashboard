const MAX_AXIS_LABEL_LENGTH = 24;

document.querySelectorAll('.ts-select').forEach((element) => {
    if (!element.tomselect) {
        new TomSelect(element, {
            plugins: ['remove_button'],
            create: false,
            maxOptions: 500,
        });
    }
});

const themeToggle = document.querySelector('[data-theme-toggle]');
if (themeToggle) {
    const syncThemeToggle = () => {
        const isDark = document.documentElement.dataset.theme === 'dark';
        themeToggle.textContent = isDark ? 'Light Mode' : 'Dark Mode';
        themeToggle.setAttribute('aria-pressed', isDark ? 'true' : 'false');
    };

    themeToggle.addEventListener('click', () => {
        const nextTheme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
        document.documentElement.dataset.theme = nextTheme;
        window.localStorage.setItem('task-dashboard-theme', nextTheme);
        syncThemeToggle();
    });

    syncThemeToggle();
}

const dynamicFilterField = document.getElementById('id_dynamic_filter_field');
if (dynamicFilterField) {
    dynamicFilterField.addEventListener('change', (event) => {
        const value = event.target.value;
        if (!value) {
            return;
        }
        const container = document.querySelector(`[data-dynamic-filter-container][data-field-name="${CSS.escape(value)}"]`);
        if (container) {
            container.classList.remove('is-collapsed');
            const select = container.querySelector('select');
            if (select && select.tomselect) {
                select.tomselect.focus();
            }
        }
        event.target.value = '';
    });
}

const periodField = document.getElementById('id_period');
if (periodField) {
    const focusDateField = document.getElementById('id_focus_date');
    const startDateField = document.getElementById('id_start_date');
    const endDateField = document.getElementById('id_end_date');

    const togglePeriodFields = () => {
        const isCustom = periodField.value === 'custom';
        if (focusDateField) {
            focusDateField.closest('div').hidden = isCustom;
        }
        if (startDateField) {
            startDateField.closest('div').hidden = !isCustom;
        }
        if (endDateField) {
            endDateField.closest('div').hidden = !isCustom;
        }
    };

    periodField.addEventListener('change', togglePeriodFields);
    togglePeriodFields();
}

if (window.dashboardCharts) {
    renderBarChart('summary-chart', window.dashboardCharts.summary, '#c96d38');
    renderLineChart('trend-chart', window.dashboardCharts.trend, '#143642');
    renderBarChart('weekday-chart', window.dashboardCharts.weekday, '#6f8f72');
    renderDoughnutChart('note-family-chart', window.dashboardCharts.noteFamily);
    renderHeatmap('heatmap-chart', window.dashboardCharts.heatmap || {});
}

const refreshCacheForm = document.querySelector('[data-refresh-cache-form]');
if (refreshCacheForm) {
    const submitButton = refreshCacheForm.querySelector('button[type="submit"]');
    const defaultLabel = submitButton ? submitButton.textContent : '';

    const restoreRefreshButton = () => {
        if (!submitButton) {
            return;
        }
        submitButton.disabled = false;
        submitButton.textContent = defaultLabel;
    };

    refreshCacheForm.addEventListener('submit', () => {
        if (!submitButton || submitButton.disabled) {
            return;
        }
        submitButton.disabled = true;
        submitButton.textContent = 'Refreshing...';
    });

    window.addEventListener('pageshow', restoreRefreshButton);
}

function truncateAxisLabel(value, maxLength = MAX_AXIS_LABEL_LENGTH) {
    const text = String(value ?? '');
    if (text.length <= maxLength) {
        return text;
    }
    return `${text.slice(0, Math.max(maxLength - 1, 1)).trimEnd()}…`;
}

function renderBarChart(elementId, payload, color) {
    const canvas = document.getElementById(elementId);
    if (!canvas || !payload) {
        return;
    }
    const labels = payload.labels || [];
    new Chart(canvas, {
        type: 'bar',
        data: {
            labels: labels.map((label) => truncateAxisLabel(label)),
            datasets: [{
                label: 'Hours',
                data: payload.hours,
                backgroundColor: color,
                borderRadius: 8,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        title: (items) => {
                            const label = labels[items[0]?.dataIndex];
                            return label === undefined ? '' : String(label);
                        },
                    },
                },
            },
            scales: {
                x: {
                    ticks: {
                        maxRotation: 45,
                        minRotation: 0,
                        autoSkip: false,
                    },
                },
                y: {
                    beginAtZero: true,
                },
            },
        },
    });
}

function renderLineChart(elementId, payload, color) {
    const canvas = document.getElementById(elementId);
    if (!canvas || !payload) {
        return;
    }
    new Chart(canvas, {
        type: 'line',
        data: {
            labels: payload.labels,
            datasets: [{
                label: 'Hours',
                data: payload.hours,
                fill: true,
                borderColor: color,
                backgroundColor: 'rgba(20, 54, 66, 0.12)',
                tension: 0.25,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
        },
    });
}

function renderDoughnutChart(elementId, payload) {
    const canvas = document.getElementById(elementId);
    if (!canvas || !payload) {
        return;
    }
    new Chart(canvas, {
        type: 'doughnut',
        data: {
            labels: payload.labels,
            datasets: [{
                data: payload.hours,
                backgroundColor: ['#143642', '#c96d38', '#6f8f72', '#9db4c0', '#e0c38a', '#7b5c61', '#49759c', '#bc6c25'],
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
        },
    });
}

function renderHeatmap(elementId, payload) {
    const container = document.getElementById(elementId);
    if (!container || !payload || !payload.cells || !payload.cells.length) {
        return;
    }
    const cells = payload.cells;
    const maxHours = Math.max(...cells.map((cell) => cell.hours), 0);
    container.replaceChildren();
    container.style.setProperty('--heatmap-columns', payload.column_count);

    const topLeft = document.createElement('div');
    topLeft.className = 'heatmap-cell heatmap-axis';
    topLeft.title = `${payload.row_label} vs ${payload.column_label}`;
    container.appendChild(topLeft);

    for (const columnLabel of payload.column_labels) {
        const header = document.createElement('div');
        header.className = 'heatmap-cell heatmap-axis';
        header.textContent = columnLabel;
        header.title = payload.column_label;
        container.appendChild(header);
    }

    for (let rowIndex = 0; rowIndex < payload.row_count; rowIndex += 1) {
        const rowLabel = document.createElement('div');
        rowLabel.className = 'heatmap-cell heatmap-axis';
        rowLabel.textContent = payload.row_labels[rowIndex] || '';
        rowLabel.title = payload.row_label;
        container.appendChild(rowLabel);

        for (let columnIndex = 0; columnIndex < payload.column_count; columnIndex += 1) {
            const match = cells.find((cell) => cell.row === rowIndex && cell.column === columnIndex);
            const value = match ? match.hours : 0;
            const intensity = maxHours ? value / maxHours : 0;
            const cell = document.createElement('div');
            cell.className = 'heatmap-cell heatmap-value';
            cell.style.background = `rgba(201, 109, 56, ${0.12 + intensity * 0.88})`;
            cell.title = `${match ? match.row_label : ''} ${match ? match.column_label : ''} - ${value.toFixed(2)} h`;
            cell.textContent = value ? value.toFixed(1) : '';
            container.appendChild(cell);
        }
    }
}
