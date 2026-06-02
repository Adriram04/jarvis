const normalizePrinterState = (state) => String(state || '').trim().toLowerCase().replace(/[_-]+/g, ' ');

export const formatPrinterState = (state, fallback = 'Sin impresion activa') => {
    const normalized = normalizePrinterState(state);
    if (!normalized) return fallback;

    if (normalized.includes('paus')) return 'En pausa';
    if (normalized.includes('not print')) return 'Inactiva';
    if (normalized.includes('print')) return 'Imprimiendo';
    if (normalized.includes('heat') || normalized.includes('warm')) return 'Calentando';
    if (normalized.includes('slice')) return 'Preparando impresion';
    if (normalized.includes('complete') || normalized.includes('finish') || normalized.includes('done')) return 'Completada';
    if (normalized.includes('cancel')) return 'Cancelada';
    if (normalized.includes('error') || normalized.includes('fail')) return 'Error';
    if (normalized.includes('idle') || normalized.includes('standby') || normalized.includes('ready')) return 'Inactiva';

    return String(state || fallback).trim() || fallback;
};

export const isActivePrinterState = (state) => {
    const normalized = normalizePrinterState(state);
    if (!normalized || normalized.includes('not print')) return false;
    return normalized.includes('print') || normalized.includes('paus') || normalized.includes('heat');
};

export const isFinishedOrIdlePrinterState = (state) => {
    const normalized = normalizePrinterState(state);
    return (
        normalized.includes('idle') ||
        normalized.includes('standby') ||
        normalized.includes('ready') ||
        normalized.includes('complete') ||
        normalized.includes('finish') ||
        normalized.includes('done') ||
        normalized.includes('cancel') ||
        normalized.includes('error') ||
        normalized.includes('fail')
    );
};
