#!/usr/bin/env python3

import socket  # Module for network communication
import struct  # Module for handling binary data
import time  # Module for timing operations
import threading  # Module for multi-threading
import sys  # Module for system-specific functions like exiting the script

# Protocol constants
MAGIC_COOKIE = 0xabcddcba  # Unique identifier for communication packets
MSG_TYPE_OFFER = 0x2  # Message type for server offers
MSG_TYPE_REQUEST = 0x3  # Message type for client requests
MSG_TYPE_PAYLOAD = 0x4  # Message type for server payloads

# Port numbers
BROADCAST_PORT = 13117  # Port to receive server offers
UDP_LISTEN_PORT = 13117  # Port for listening to UDP broadcasts

class TransferResult:
    """
    Class to store the result of a single transfer (TCP or UDP).
    """
    def __init__(self, protocol, index):
        self.protocol = protocol  # Protocol type: "TCP" or "UDP"
        self.index = index  # Transfer number (e.g., #1, #2, etc.)
        self.start_time = 0.0  # Time when the transfer started
        self.end_time = 0.0  # Time when the transfer ended
        self.bytes_received = 0  # Total bytes received
        self.percentage_received = 100.0  # Percentage of packets received (for UDP)

    def duration(self):
        return self.end_time - self.start_time  # Calculate the duration of the transfer

    def bits_per_second(self):
        total_bits = self.bytes_received * 8  # Convert bytes to bits
        d = self.duration()  # Calculate the duration
        return total_bits / d if d > 0 else 0.0  # Return speed in bits/second

def handle_tcp_download(server_ip, tcp_port, file_size, result_obj):
    """
    Handle a TCP download request.

    :param server_ip: IP address of the server.
    :param tcp_port: TCP port on which the server listens.
    :param file_size: Total bytes to request from the server.
    :param result_obj: Object to store the result of this transfer.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # Create a TCP socket
        s.connect((server_ip, tcp_port))  # Connect to the server

        request_str = f"{file_size}\n"  # Prepare the file size request string
        s.sendall(request_str.encode('utf-8'))  # Send the request to the server

        start = time.perf_counter()  # Start high-resolution timing

        bytes_received = 0  # Initialize the received byte counter
        while bytes_received < file_size:  # Loop until the requested size is received
            chunk = s.recv(4096)  # Receive data in 4096-byte chunks
            if not chunk:
                break  # Stop if the server closes the connection
            bytes_received += len(chunk)  # Update the byte counter

        end = time.perf_counter()  # Stop timing
        s.close()  # Close the socket

        # Store results in the result object
        result_obj.start_time = start
        result_obj.end_time = end
        result_obj.bytes_received = bytes_received

    except Exception as e:
        result_obj.end_time = time.perf_counter()  # Record the end time on error
        print(f"[TCP Thread] Error: {e}")  # Print the error message

def handle_udp_download(server_ip, udp_port, file_size, result_obj):
    """
    Handle a UDP download request.

    :param server_ip: IP address of the server.
    :param udp_port: UDP port on which the server listens.
    :param file_size: Total bytes to request from the server.
    :param result_obj: Object to store the result of this transfer.
    """
    try:
        udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # Create a UDP socket
        udp_sock.bind(('', 0))  # Bind to any available port
        udp_sock.settimeout(1.0)  # Set a 1-second timeout for receiving data

        request_packet = struct.pack('!I B Q', MAGIC_COOKIE, MSG_TYPE_REQUEST, file_size)  # Create the request packet
        udp_sock.sendto(request_packet, (server_ip, udp_port))  # Send the request to the server

        start = time.perf_counter()  # Start high-resolution timing

        total_segments = None  # Total number of expected segments (initially unknown)
        received_segments = 0  # Counter for received segments
        bytes_received = 0  # Counter for received bytes

        while True:  # Loop to receive all segments
            try:
                data, addr = udp_sock.recvfrom(2048)  # Receive a packet (up to 2048 bytes)
                if len(data) < 21:  # Ignore packets smaller than the header size
                    continue

                magic_cookie, msg_type, t_segments, c_segment = struct.unpack('!I B Q Q', data[:21])  # Unpack the header
                if magic_cookie != MAGIC_COOKIE or msg_type != MSG_TYPE_PAYLOAD:
                    continue  # Ignore invalid packets

                if total_segments is None:
                    total_segments = t_segments  # Set the total number of segments

                payload = data[21:]  # Extract the payload data
                payload_size = len(payload)  # Calculate the size of the payload
                bytes_received += payload_size  # Update the byte counter
                received_segments += 1  # Increment the segment counter

            except socket.timeout:
                break  # Stop receiving if no data arrives within the timeout

        end = time.perf_counter()  # Stop timing

        result_obj.start_time = start  # Record the start time
        result_obj.end_time = end  # Record the end time
        result_obj.bytes_received = bytes_received  # Store the total bytes received

        if total_segments is not None and total_segments > 0:
            result_obj.percentage_received = (received_segments / total_segments) * 100.0  # Calculate packet receipt percentage
        else:
            result_obj.percentage_received = 0.0  # Set to 0% if total_segments is unknown

        udp_sock.close()  # Close the socket

    except Exception as e:
        result_obj.end_time = time.perf_counter()  # Record the end time on error
        print(f"[UDP Thread] Error: {e}")  # Print the error message

def listen_for_offers():
    """
    Listen for server broadcast offers and return the server details.

    :return: Tuple containing server IP, UDP port, and TCP port.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # Create a UDP socket
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # Allow address reuse
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)  # Enable broadcasting
    sock.bind(('', UDP_LISTEN_PORT))  # Bind to the broadcast port

    print("Client started, listening for offer requests...")

    while True:  # Listen for broadcast packets
        data, addr = sock.recvfrom(1024)  # Receive a packet (up to 1024 bytes)
        if len(data) < 9:  # Ignore packets smaller than the expected size
            continue

        magic_cookie, msg_type, udp_port, tcp_port = struct.unpack('!I B H H', data[:9])  # Unpack the offer packet
        if magic_cookie == MAGIC_COOKIE and msg_type == MSG_TYPE_OFFER:  # Validate the offer packet
            server_ip = addr[0]  # Extract the server's IP address
            print(f"Received offer from {server_ip}, UDP port = {udp_port}, TCP port = {tcp_port}")
            sock.close()  # Close the socket
            return server_ip, udp_port, tcp_port  # Return the server details

def main():
    """
    Main function to coordinate user input and file transfer operations.
    """
    while True:
        try:
            file_size = int(input("Enter file size in bytes (e.g. 1000000 for ~1MB): "))  # Request file size from the user
            tcp_count = int(input("Enter number of TCP connections: "))  # Request TCP connection count
            udp_count = int(input("Enter number of UDP connections: "))  # Request UDP connection count

            server_ip, server_udp_port, server_tcp_port = listen_for_offers()  # Wait for a server offer

            threads = []  # List to hold thread objects
            results = []  # List to hold result objects

            # Create TCP threads
            for i in range(tcp_count):
                res = TransferResult("TCP", i+1)  # Create a result object for each TCP transfer
                t = threading.Thread(
                    target=handle_tcp_download,
                    args=(server_ip, server_tcp_port, file_size, res)
                )
                threads.append(t)  # Add the thread to the list
                results.append(res)  # Add the result object to the list

            # Create UDP threads
            for j in range(udp_count):
                res = TransferResult("UDP", j+1)  # Create a result object for each UDP transfer
                t = threading.Thread(
                    target=handle_udp_download,
                    args=(server_ip, server_udp_port, file_size, res)
                )
                threads.append(t)  # Add the thread to the list
                results.append(res)  # Add the result object to the list

            for t in threads:
                t.start()  # Start all threads
            for t in threads:
                t.join()  # Wait for all threads to complete

            # Display results
            for r in results:
                if r.protocol == "TCP":
                    print(f"TCP transfer #{r.index} finished, "
                          f"total time: {r.duration():.6f} seconds, "
                          f"total speed: {r.bits_per_second():.2f} bits/second")
                else:
                    print(f"UDP transfer #{r.index} finished, "
                          f"total time: {r.duration():.6f} seconds, "
                          f"total speed: {r.bits_per_second():.2f} bits/second, "
                          f"percentage of packets received successfully: {r.percentage_received:.2f}%")

            print("All transfers complete, listening to offer requests...\n")

        except KeyboardInterrupt:
            print("\nClient shutting down.")  # Handle Ctrl+C gracefully
            sys.exit(0)  # Exit the script
        except Exception as e:
            print(f"[Client] Error: {e}")  # Print any errors

if __name__ == "__main__":
    main()  # Run the main function
