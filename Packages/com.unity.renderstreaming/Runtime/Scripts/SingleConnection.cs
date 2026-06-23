using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace Unity.RenderStreaming
{
    public class SingleConnection : SignalingHandlerBase,
        ICreatedConnectionHandler, IDeletedConnectionHandler,
        IAddReceiverHandler, IOfferHandler, IAddChannelHandler
    {
        [SerializeField] private List<Component> streams = new List<Component>();

        private string connectionId;

        public override IEnumerable<Component> Streams => streams;

        public void AddComponent(Component component)
        {
            streams.Add(component);
        }

        public void RemoveComponent(Component component)
        {
            streams.Remove(component);
        }

        public override void CreateConnection(string connectionId)
        {
            this.connectionId = connectionId;
            base.CreateConnection(connectionId);
        }

        public override void DeleteConnection(string connectionId)
        {
            if (this.connectionId != connectionId)
                return;
            Disconnect(connectionId);
            base.DeleteConnection(connectionId);
            this.connectionId = null;
        }

        public void OnCreatedConnection(SignalingEventData data)
        {
            // Accept first incoming connection when connectionId is not pre-set
            if (string.IsNullOrEmpty(connectionId))
            {
                connectionId = data.connectionId;
            }
            else if (data.connectionId != connectionId)
            {
                return;
            }

            foreach (var sender in streams.OfType<IStreamSender>())
            {
                AddSender(data.connectionId, sender);
            }
            foreach (var channel in streams.OfType<IDataChannel>().Where(c => c.IsLocal))
            {
                AddChannel(connectionId, channel);
            }
            // Explicitly trigger offer after adding senders
            StartCoroutine(SendOfferAfterTracks(data.connectionId));
        }

        private System.Collections.IEnumerator SendOfferAfterTracks(string cid)
        {
            yield return new WaitForSeconds(0.5f);
            SendOffer(cid);
        }

        public void OnDeletedConnection(SignalingEventData data)
        {
            if (data.connectionId != connectionId)
                return;
            Disconnect(connectionId);
            connectionId = null;
        }

        private void Disconnect(string connectionId)
        {
            foreach (var sender in streams.OfType<IStreamSender>())
            {
                RemoveSender(connectionId, sender);
            }

            foreach (var receiver in streams.OfType<IStreamReceiver>())
            {
                RemoveReceiver(connectionId, receiver);
            }

            foreach (var channel in streams.OfType<IDataChannel>())
            {
                RemoveChannel(connectionId, channel);
            }
        }

        public void OnOffer(SignalingEventData data)
        {
            if (data.connectionId != connectionId)
                return;
            SendAnswer(data.connectionId);
        }

        public void OnAddReceiver(SignalingEventData data)
        {
            if (data.connectionId != connectionId)
                return;

            var track = data.transceiver.Receiver.Track;
            IStreamReceiver receiver = GetReceiver(track.Kind);
            SetReceiver(data.connectionId, receiver, data.transceiver);
        }

        public void OnAddChannel(SignalingEventData data)
        {
            if (data.connectionId != connectionId)
                return;
            var channel = streams.OfType<IDataChannel>().FirstOrDefault(r => !r.IsConnected && !r.IsLocal);
            channel?.SetChannel(connectionId, data.channel);
        }

        IStreamReceiver GetReceiver(WebRTC.TrackKind kind)
        {
            if (kind == WebRTC.TrackKind.Audio)
                return streams.OfType<AudioStreamReceiver>().First();
            if (kind == WebRTC.TrackKind.Video)
                return streams.OfType<VideoStreamReceiver>().First();
            throw new System.ArgumentException();
        }
    }
}
