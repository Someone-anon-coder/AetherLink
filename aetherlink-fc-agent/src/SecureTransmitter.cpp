#include "SecureTransmitter.h"
#include <iostream>

namespace ssl = boost::asio::ssl;
using boost::asio::ip::tcp;

SecureTransmitter::SecureTransmitter(const std::string& address, short port)
    : _ssl_context(ssl::context::tlsv13_client),
      _address(address),
      _port(port) {
    _ssl_context.set_verify_mode(ssl::verify_peer);
    try {
        _ssl_context.load_verify_file("certs/ca.crt");
        _ssl_context.use_certificate_chain_file("certs/client.crt");
        _ssl_context.use_private_key_file("certs/client.key", ssl::context::pem);
    } catch (const std::exception& e) {
        std::cerr << "Certificate loading failed: " << e.what() << std::endl;
    }
}

bool SecureTransmitter::connect() {
    try {
        tcp::resolver resolver(_io_context);
        auto endpoints = resolver.resolve(_address, std::to_string(_port));

        _ssl_stream = std::make_unique<ssl::stream<tcp::socket>>(_io_context, _ssl_context);
        boost::asio::connect(_ssl_stream->next_layer(), endpoints);
        _ssl_stream->handshake(ssl::stream_base::client);

        std::cout << "Successfully connected to Ground Station!" << std::endl;
        return true;
    } catch (const std::exception& e) {
        std::cerr << "Connection failed: " << e.what() << std::endl;
        return false;
    }
}

void SecureTransmitter::send(const std::string& data) {
    try {
        size_t bytes_sent = boost::asio::write(*_ssl_stream, boost::asio::buffer(data));
        std::cout << "Sent " << bytes_sent << " bytes of telemetry data." << std::endl;
    } catch (const std::exception& e) {
        std::cerr << "Write failed: " << e.what() << std::endl;
    }
}
