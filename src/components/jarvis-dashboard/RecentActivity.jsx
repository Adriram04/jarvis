import React from 'react';
import { CheckCircle2 } from 'lucide-react';

const RecentActivity = ({ items = [] }) => {
    return (
        <section className="jarvis-panel jarvis-recent-activity">
            <div className="jarvis-panel-title">Actividad reciente</div>
            <div className="jarvis-activity-list">
                {items.map((item) => (
                    <article className="jarvis-activity-item" key={`${item.title}-${item.time}`}>
                        <CheckCircle2 size={15} />
                        <div>
                            <strong>{item.title}</strong>
                            <span>{item.meta}</span>
                        </div>
                        <time>{item.time}</time>
                    </article>
                ))}
            </div>
        </section>
    );
};

export default RecentActivity;
