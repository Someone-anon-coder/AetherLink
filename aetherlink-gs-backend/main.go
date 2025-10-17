package main

import (
	"crypto/tls"
	"crypto/x509"
	"fmt"
	"io"
	"log"
	"net"
	"os"

	"google.golang.org/protobuf/proto"
	pb "aetherlink-gs-backend/proto"
)

func handleConnection(conn net.Conn) {
	defer conn.Close()
	log.Printf("New connection from: %s", conn.RemoteAddr())

	for {
		buf := make([]byte, 1024)
		n, err := conn.Read(buf)
		if err != nil {
			if err == io.EOF {
				log.Printf("Client disconnected: %s", conn.RemoteAddr())
				return
			}
			log.Printf("Error reading from connection: %v", err)
			return
		}

		telemetry := &pb.AetherLinkTelemetry{}
		if err := proto.Unmarshal(buf[:n], telemetry); err != nil {
			log.Printf("Error deserializing data: %v", err)
			continue
		}

		fmt.Printf("Received Telemetry: {Roll: %.2f, Pitch: %.2f, Yaw: %.2f, Latitude: %.3f, Longitude: %.3f, Altitude: %.2f}\n",
			telemetry.RollDeg, telemetry.PitchDeg, telemetry.YawDeg, telemetry.LatitudeDeg, telemetry.LongitudeDeg, telemetry.RelativeAltitudeM)
	}
}

func main() {
	cert, err := tls.LoadX509KeyPair("certs/server.crt", "certs/server.key")
	if err != nil {
		log.Fatalf("Failed to load server key pair: %v", err)
	}

	caCert, err := os.ReadFile("certs/ca.crt")
	if err != nil {
		log.Fatalf("Failed to read CA certificate: %v", err)
	}
	caCertPool := x509.NewCertPool()
	caCertPool.AppendCertsFromPEM(caCert)

	tlsConfig := &tls.Config{
		Certificates: []tls.Certificate{cert},
		ClientCAs:    caCertPool,
		ClientAuth:   tls.RequireAndVerifyClientCert,
	}

	listener, err := tls.Listen("tcp", ":50051", tlsConfig)
	if err != nil {
		log.Fatalf("Failed to start TLS listener: %v", err)
	}
	defer listener.Close()
	log.Println("mTLS server listening on :50051")

	for {
		conn, err := listener.Accept()
		if err != nil {
			log.Printf("Failed to accept connection: %v", err)
			continue
		}
		go handleConnection(conn)
	}
}
