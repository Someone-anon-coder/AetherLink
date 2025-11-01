#ifndef SECURE_TRANSMITTER_H
#define SECURE_TRANSMITTER_H

#include <boost/asio.hpp>
#include <boost/asio/ssl.hpp>
#include <string>
#include <memory>

class SecureTransmitter {
public:
    SecureTransmitter(const std::string& address, uint16_t port);
    bool connect();
    void send(const std::string& data);

private:
    boost::asio::io_context _io_context;
    boost::asio::ssl::context _ssl_context;
    std::unique_ptr<boost::asio::ssl::stream<boost::asio::ip::tcp::socket>> _ssl_stream;
    std::string _address;
    uint16_t _port;
};

#endif // SECURE_TRANSMITTER_H
