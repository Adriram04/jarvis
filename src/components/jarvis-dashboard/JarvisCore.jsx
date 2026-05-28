import React from 'react';
import { motion } from 'framer-motion';

const JarvisCore = ({ isListening, audioLevel = 0, compact = false }) => {
    const pulseScale = isListening ? 1.08 + Math.min(audioLevel, 0.22) : 1;

    return (
        <div className={`jarvis-core ${compact ? 'jarvis-core-compact' : ''} ${isListening ? 'is-listening' : ''}`}>
            <motion.div
                className="jarvis-core-ring ring-one"
                animate={{ rotate: 360 }}
                transition={{ duration: 26, repeat: Infinity, ease: 'linear' }}
            />
            <motion.div
                className="jarvis-core-ring ring-two"
                animate={{ rotate: -360 }}
                transition={{ duration: 18, repeat: Infinity, ease: 'linear' }}
            />
            <motion.div
                className="jarvis-core-ring ring-three"
                animate={{ rotate: 360 }}
                transition={{ duration: 34, repeat: Infinity, ease: 'linear' }}
            />
            <motion.div
                className="jarvis-core-avatar"
                animate={{ scale: pulseScale }}
                transition={{ duration: 1.6, repeat: Infinity, repeatType: 'reverse', ease: 'easeInOut' }}
            >
                <div className="jarvis-core-face">
                    <span />
                    <span />
                </div>
            </motion.div>
            <div className="jarvis-core-platform" aria-hidden="true" />
        </div>
    );
};

export default JarvisCore;
