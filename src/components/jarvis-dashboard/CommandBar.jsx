import React from 'react';
import { Mic, MicOff, Send } from 'lucide-react';

const CommandBar = ({
    value,
    onChange,
    onSubmit,
    onToggleListening,
    isListening,
    isConnected,
    placeholder = 'Habla o escribe tu comando...',
}) => {
    const handleSubmit = (event) => {
        event.preventDefault();
        onSubmit();
    };

    return (
        <form className="jarvis-command-bar" onSubmit={handleSubmit}>
            <input
                value={value}
                onChange={(event) => onChange(event.target.value)}
                placeholder={placeholder}
                aria-label="Comando para Jarvis"
            />
            <button type="submit" className="jarvis-icon-button" title="Enviar comando">
                <Send size={18} />
            </button>
            <button
                type="button"
                className={`jarvis-icon-button ${isListening ? 'is-active' : ''}`}
                onClick={onToggleListening}
                title={isListening ? 'Pausar microfono' : isConnected ? 'Activar microfono' : 'Conectar y activar microfono'}
            >
                {isListening ? <Mic size={18} /> : <MicOff size={18} />}
            </button>
        </form>
    );
};

export default CommandBar;
