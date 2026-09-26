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
  # Dotenv::VERSION does not exist in 2.x, and the version matters here: the
  # gem stopped expanding \n inside double quotes somewhere between 2.8 and
  # 3.2, so two boxes with "the same" parser give different answers.
  version = if defined?(Dotenv::VERSION)
              Dotenv::VERSION
            else
              spec = Gem.loaded_specs['dotenv']
              spec && spec.version.to_s
            end
  out({ 'values' => Dotenv.parse(ARGV[0]), 'version' => version })
rescue => e
  out({ 'error' => "#{e.class}: #{e.message}" })
end
