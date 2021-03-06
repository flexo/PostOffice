import sys
import time
import os
import socket
import traceback
import argparse
import getpass
import gnupg
from daemonize import Daemonize

CONNECTION_LIMIT = 20
CUPS_CONNECTION = None

PASSPHRASE = None

def check_rate_limit(connection_ip):
    '''Checks previous connections and rejects this one if connected too over
    some number of times today.
    Returns True if connection allowed, false if not.

    Delete last line: https://stackoverflow.com/a/10289740
    '''
    #TODO have one variable with the date/time string and use that instead of
    #multiple calls to strftime

    try:
        rate_limit_file = open(connection_ip+".rate", "r+")
    except FileNotFoundError:
        rate_limit_file = open(connection_ip+".rate", "a+")

    #This is really slow, apparently. But we probably don't care much.
    last = ""
    for last in rate_limit_file:
        pass

    if last.split(" ")[0] == time.strftime("%d/%m/%Y"):
        #Check the existing value for today
        if int(last.split(" ")[1]) >= CONNECTION_LIMIT:
            #Return false if we've exceeded the limit
            rate_limit_file.close()
            return False
        else:
            #Increment it
            previous_val = int(last.split(" ")[1])
            rate_limit_file.seek(0, os.SEEK_END)
            pos = rate_limit_file.tell() - 1
            while pos > 0 and rate_limit_file.read(1) != "\n":
                pos -= 1
                rate_limit_file.seek(pos, os.SEEK_SET)

            if pos > 0:
                rate_limit_file.seek(pos, os.SEEK_SET)
                rate_limit_file.truncate()

            rate_limit_file.write("\n"+time.strftime("%d/%m/%Y")+" "+str(previous_val+1))
    elif last.split(" ")[0] != time.strftime("%d/%m/%Y"):
        #Add a new date if it doesnt exist yet.
        rate_limit_file.close()
        rate_limit_file = open(connection_ip+".rate", "a")

        rate_limit_file.writelines(time.strftime("%d/%m/%Y")+" "+str(1)+"\n")

    rate_limit_file.close()

    return True

def write_file(string, ip_addr, date):
    '''Saves the passed string to a file.
    File name is: <ip_addrv4>_<d/m/Y>
    Return filename.
    '''
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)

    filename = os.path.join(log_dir, ip_addr + "_" + date)

    with open(filename, "w+") as message_file:
        message_file.write("------------\n"+ip_addr+"\n"+date+"\n------------\n")
        message_file.write(string)
        message_file.write("\n------------")

    return filename

def print_file(filename):
    '''Sends the file to the printer '''
    if CUPS_CONNECTION is None:
        return

    default = CUPS_CONNECTION.getDefault()
    if default == None:
        raise IOError("No default printer")

    return CUPS_CONNECTION.printFile(default, filename, filename, dict())

def parse_string(string):
    '''Parses the printable bytes with an attempt to find
    one of the special strings we can handle'''

    gpg = gnupg.GPG()

    if "-----BEGIN PGP MESSAGE----" in string[:30]:
        message_decrypted = gpg.decrypt(string, passphrase=PASSPHRASE)

        return str(message_decrypted)

    return string

def await_connections():
    '''Await connections from the outside
    and take all actions necessary to print
    our content '''
    #Uncomment the below to accept non-localhost connections
    #IP = "0.0.0.0"
    IP = "127.0.0.1"
    PORT = 7878

    buffer_size = 1024

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((IP, PORT))

    while True:
        sock.listen(1)

        conn, addr = sock.accept()

        if check_rate_limit(addr[0]):
            received_bytes = conn.recv(buffer_size)

            # If we can't decode whatever the user has sent us, we should close
            # the connection immediately.  Don't just error out here.
            try:
                received_string = received_bytes.decode("utf-8")
            except UnicodeDecodeError as err:
                print("Error decoding received bytes %r (%s)" % (received_bytes, err))
                conn.close()
                continue

            filename = write_file(parse_string(received_string), addr[0], time.strftime("%d-%m-%Y-%H-%M%p"))

            print_file(filename)

            conn.send(b"OK")

            conn.close()

        else:

            conn.close()


if __name__ == "__main__":

    pid = "/tmp/postoffice.pid"
    daemon = False
    cups = False
    PASSPHRASE = getpass.getpass('Password for GPG: ')

    parser = argparse.ArgumentParser(description='A one way telegram machine!')
    parser.add_argument('-d', dest='daemon', action='store_true',
                        help='Daemonize the process')
    parser.add_argument('-P', '--no-printer', dest='printer',
                        action='store_false',
                        help="Don't send files to the printer")
    args = parser.parse_args(sys.argv[1:])

    if args.printer:
        try:
            import cups
            CUPS_CONNECTION = cups.Connection()
        except (ImportError, RuntimeError) as e:
            print('Error initialising CUPS:', file=sys.stderr)
            print(traceback.format_exc(), file=sys.stderr)
            print("Cups connection will be mocked.", file=sys.stderr)

    if args.daemon:
        print("Daemonizing....")
        daemon = Daemonize(app="PostOffice", pid=pid, action=await_connections)
        daemon.start()
    else:
        await_connections()
