import React from 'react';
import CapabilitiesPanel from '../CapabilitiesPanel';
import CommandBar from '../CommandBar';
import JarvisCore from '../JarvisCore';
import QuickActions from '../QuickActions';
import StatusCard from '../StatusCard';

const HomeModule = ({ context, actions }) => {
    const {
        capabilities,
        connections,
        inputValue,
        isConnected,
        isListening,
        setInputValue,
        systemItems,
        audioLevel,
    } = context;

    return (
        <section className="jarvis-module home">
            <div className="jarvis-core-stage module-home-stage">
                <StatusCard title="Estado del sistema" items={systemItems} className="floating left" />
                <JarvisCore isListening={isListening} audioLevel={audioLevel} />
                <StatusCard title="Conexiones activas" items={connections} className="floating right" />
            </div>

            <CommandBar
                value={inputValue}
                onChange={setInputValue}
                onSubmit={actions.onCommandSubmit}
                onToggleListening={actions.onToggleListening}
                isListening={isListening}
                isConnected={isConnected}
            />

            <CapabilitiesPanel capabilities={capabilities} onAction={actions.onQuickAction} />
            <QuickActions onAction={actions.onQuickAction} />
        </section>
    );
};

export default HomeModule;
