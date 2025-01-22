#!/usr/bin/env python3
import socket  # For network socket operations
import struct  # For packing/unpacking binary data
import threading  # For concurrency
import time  # For sleep intervals between broadcasts
import os  # For os.urandom (used to generate random bytes)

# Constant values used throughout the script
MAGIC_COOKIE = 0xabcddcba  # 4-byte magic cookie to identify packets
MSG_TYPE_OFFER = 0x2  # 1-byte message type for server offers
MSG_TYPE_REQUEST = 0x3  # 1-byte message type for client requests
MSG_TYPE_PAYLOAD = 0x4  # 1-byte message type for server payloads
BROADCAST_PORT = 13117  # Port for sending or receiving offer broadcasts
BROADCAST_INTERVAL = 1.0  # Interval (in seconds) between broadcasts
SERVER_TCP_PORT = 55000  # Port for the server's TCP listener
SERVER_UDP_PORT = 56000  # Port for the server's UDP listener

def broadcast_offers():
    """
    Continuously broadcasts an offer packet (4 + 1 + 2 + 2 = 9 bytes) to the
    broadcast address <broadcast> on port BROADCAST_PORT every BROADCAST_INTERVAL seconds.
    """
    broadcast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # Create a UDP socket for broadcasting
    broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)  # Enable broadcast capability
    offer_packet = struct.pack('!I B H H', MAGIC_COOKIE, MSG_TYPE_OFFER, SERVER_UDP_PORT, SERVER_TCP_PORT)  # Prepare the offer packet
    while True:
        try:
            broadcast_socket.sendto(offer_packet, ('<broadcast>', BROADCAST_PORT))  # Send the offer packet to the broadcast address
            time.sleep(BROADCAST_INTERVAL)  # Wait for the specified interval before sending the next packet
        except Exception as e:
            print(f"[Broadcast Thread] Error: {e}")  # Log any errors during broadcasting
            break  # Exit the loop if an error occurs

def handle_tcp_connection(client_socket, client_address):
    """
    Handle one TCP connection from a client:

    1. Read the requested file size (as a newline-terminated string).
    2. Send exactly that many bytes to the client in chunks.
    3. Close the connection.

    :param client_socket: A socket connected to the client.
    :param client_address: (ip, port) of the client.
    """
    try:
        data_buffer = b''  # Initialize a buffer to store incoming data
        while b'\n' not in data_buffer:  # Read data until a newline character is found
            chunk = client_socket.recv(1024)  # Receive data in chunks of 1024 bytes
            if not chunk:
                break  # Break if the client closes the connection
            data_buffer += chunk  # Append the received chunk to the buffer

        file_size_str = data_buffer.decode().strip()  # Decode the buffer and strip whitespace/newline
        requested_size = int(file_size_str)  # Convert the file size string to an integer
        bytes_sent = 0  # Initialize a counter for the number of bytes sent
        buffer_size = 4096  # Set the size of each chunk to send
        while bytes_sent < requested_size:  # Loop until the requested size is sent
            remaining = requested_size - bytes_sent  # Calculate the remaining bytes to send
            send_size = min(buffer_size, remaining)  # Determine the size of the next chunk to send
            random_chunk = os.urandom(send_size)  # Generate a random chunk of bytes
            sent = client_socket.send(random_chunk)  # Send the chunk to the client
            bytes_sent += sent  # Update the counter with the number of bytes sent
        client_socket.close()  # Close the client socket after sending all data
    except Exception as e:
        print(f"[TCP Handler] Error with client {client_address}: {e}")  # Log any errors
        client_socket.close()  # Close the client socket in case of an error

def handle_udp_request(client_address, requested_size, server_udp_socket):
    """
    Handle a UDP request from the client:

    1. Break the requested size into segments of ~1024 bytes.
    2. For each segment, build a 21-byte header + payload.
    3. Send each payload via UDP to the client.

    :param client_address: The (ip, port) where the client's UDP socket is bound.
    :param requested_size: Total bytes the client wants.
    :param server_udp_socket: The server-side UDP socket to send from.
    """
    try:
        chunk_size = 1024  # Set the size of each UDP segment
        total_segments = (requested_size + chunk_size - 1) // chunk_size  # Calculate the total number of segments
        current_segment = 0  # Initialize the segment counter
        bytes_sent = 0  # Initialize the counter for bytes sent
        while bytes_sent < requested_size:  # Loop until all requested bytes are sent
            remaining = requested_size - bytes_sent  # Calculate the remaining bytes to send
            send_size = min(chunk_size, remaining)  # Determine the size of the next segment to send
            random_chunk = os.urandom(send_size)  # Generate a random chunk of bytes
            header = struct.pack('!I B Q Q', MAGIC_COOKIE, MSG_TYPE_PAYLOAD, total_segments, current_segment)  # Build the 21-byte header
            payload_packet = header + random_chunk  # Combine the header and payload
            server_udp_socket.sendto(payload_packet, client_address)  # Send the packet to the client
            bytes_sent += send_size  # Update the counter with the number of bytes sent
            current_segment += 1  # Increment the segment counter
    except Exception as e:
        print(f"[UDP Handler] Error sending data to {client_address}: {e}")  # Log any errors

def udp_listener():
    """
    Listen for incoming UDP 'request' packets on SERVER_UDP_PORT,
    then spawn a thread to serve each request.
    """
    server_udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # Create a UDP socket for listening
    server_udp_socket.bind(('', SERVER_UDP_PORT))  # Bind the socket to the UDP port on all interfaces
    while True:
        try:
            data, addr = server_udp_socket.recvfrom(1024)  # Receive data from a client (up to 1024 bytes)
            if len(data) < 13:  # Ensure the packet is large enough to contain header fields
                continue  # Ignore invalid packets
            magic_cookie, msg_type = struct.unpack('!I B', data[:5])  # Extract the magic cookie and message type
            if magic_cookie != MAGIC_COOKIE or msg_type != MSG_TYPE_REQUEST:  # Validate the magic cookie and message type
                continue  # Ignore invalid packets
            requested_size = struct.unpack('!Q', data[5:13])[0]  # Extract the requested file size
            threading.Thread(target=handle_udp_request, args=(addr, requested_size, server_udp_socket), daemon=True).start()  # Start a thread to handle the request
        except Exception as e:
            print(f"[UDP Listener] Error: {e}")  # Log any errors

def tcp_listener():
    """
    Listen for incoming TCP connections on SERVER_TCP_PORT,
    spawn a thread for each new client.
    """
    server_tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # Create a TCP socket for listening
    server_tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # Allow the socket to be reused
    server_tcp_socket.bind(('', SERVER_TCP_PORT))  # Bind the socket to the TCP port on all interfaces
    server_tcp_socket.listen(5)  # Start listening for incoming connections (backlog of 5)
    while True:
        try:
            client_socket, client_address = server_tcp_socket.accept()  # Accept a new client connection
            threading.Thread(target=handle_tcp_connection, args=(client_socket, client_address), daemon=True).start()  # Start a thread to handle the client
        except Exception as e:
            print(f"[TCP Listener] Error: {e}")  # Log any errors

def main():
    """
    Main server routine:
    1. Print local IP.
    2. Start a thread to broadcast offers.
    3. Start a thread for UDP listener.
    4. Start a thread for TCP listener.
    5. Run forever (until KeyboardInterrupt).
    """
    hostname = socket.gethostname()  # Get the hostname of the server
    local_ip = socket.gethostbyname(hostname)  # Get the local IP address of the server
    print(f"Server started, listening on IP address {local_ip}")  # Print the server's IP address
    threading.Thread(target=broadcast_offers, daemon=True).start()  # Start the broadcasting thread
    threading.Thread(target=udp_listener, daemon=True).start()  # Start the UDP listener thread
    threading.Thread(target=tcp_listener, daemon=True).start()  # Start the TCP listener thread
    try:
        while True:
            time.sleep(1)  # Keep the main thread alive
    except KeyboardInterrupt:
        print("\nServer shutting down.")  # Print a message when the server is shutting down

if __name__ == "__main__":
    main()  # Run the main function