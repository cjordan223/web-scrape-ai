import { useNavigate } from 'react-router-dom';
import IngestTab from './IngestTab';

export default function IngestView() {
    const navigate = useNavigate();

    return (
        <div style={{ height: 'calc(100vh - 56px)', overflow: 'hidden' }}>
            <IngestTab onSentToQa={() => navigate('/pipeline/qa')} />
        </div>
    );
}
