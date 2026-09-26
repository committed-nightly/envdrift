# The Ruby `dotenv` gem. Dotenv.parse runs command substitution on values, so
# envdrift treats this engine as one that executes the file (see hazards.py).
require 'json'

def out(o)
  $stdout.write(JSON.dump(o))
end

begin
  require 'dotenv'
rescue LoadError => e
  out({ 'unavailable' => "the `dotenv` gem is not installed: #{e.message}" })
  exit 0
end

begin
  version = (defined?(Dotenv::VERSION) ? Dotenv::VERSION : nil)
  out({ 'values' => Dotenv.parse(ARGV[0]), 'version' => version })
rescue => e
  out({ 'error' => "#{e.class}: #{e.message}" })
end
